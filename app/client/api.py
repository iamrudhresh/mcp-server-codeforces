"""
High-level Codeforces operations — the Python mirror of `src/api.js`.

Every function returns plain JSON-serializable dicts with the same field names
as the Node runtime, so both runtimes are interchangeable for an MCP client.
Large upstream payloads are always compacted and capped.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from app.client.http import assert_handle, call_api, health_snapshot
from app.client.normalize import (
    normalize_problem_id,
    normalize_problemset,
    rating_tier,
    search_problems,
)
from app.config import config
from app.utils.errors import CodeforcesError, error_layer

ADAPTER_VERSION = "1.0.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(seconds: Optional[int]) -> Optional[str]:
    if not seconds:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def _clamp(value: Any, low: int, high: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def _compact_submission(s: dict) -> dict:
    """Trim a raw submission; the raw objects embed the whole problem + authors."""
    problem = s.get("problem") or {}
    author = s.get("author") or {}
    identity = problem.get("contestId") or problem.get("problemsetName")
    return {
        "id": s.get("id"),
        "contestId": s.get("contestId"),
        "problem": f"{identity}/{problem.get('index')}" if problem else None,
        "problemName": problem.get("name"),
        "problemRating": problem.get("rating"),
        "tags": problem.get("tags") or [],
        "handle": [m.get("handle") for m in author.get("members") or []],
        "participantType": author.get("participantType"),
        "language": s.get("programmingLanguage"),
        "verdict": s.get("verdict", "TESTING"),
        "passedTestCount": s.get("passedTestCount"),
        "timeConsumedMillis": s.get("timeConsumedMillis"),
        "memoryConsumedBytes": s.get("memoryConsumedBytes"),
        "creationTime": _iso(s.get("creationTimeSeconds")),
    }


def _compact_contest(c: dict) -> dict:
    duration = c.get("durationSeconds")
    return {
        "id": c.get("id"),
        "name": c.get("name"),
        "type": c.get("type"),
        "phase": c.get("phase"),
        "frozen": c.get("frozen", False),
        "durationMinutes": round(duration / 60) if duration else None,
        "startTime": _iso(c.get("startTimeSeconds")),
        "relativeTimeSeconds": c.get("relativeTimeSeconds"),
        "difficulty": c.get("difficulty"),
        "url": f"https://codeforces.com/contest/{c.get('id')}",
    }


def _compact_user(u: dict) -> dict:
    tier = rating_tier(u.get("rating"))
    return {
        "handle": u.get("handle"),
        "firstName": u.get("firstName"),
        "lastName": u.get("lastName"),
        "country": u.get("country"),
        "city": u.get("city"),
        "organization": u.get("organization"),
        "rating": u.get("rating"),
        "maxRating": u.get("maxRating"),
        "rank": u.get("rank"),
        "maxRank": u.get("maxRank"),
        "tier": tier["tier"] if tier else None,
        "contribution": u.get("contribution", 0),
        "friendOfCount": u.get("friendOfCount", 0),
        "registrationTime": _iso(u.get("registrationTimeSeconds")),
        "lastOnline": _iso(u.get("lastOnlineTimeSeconds")),
        "avatar": u.get("titlePhoto") or u.get("avatar"),
        "profileUrl": f"https://codeforces.com/profile/{u.get('handle')}",
    }


# ── Problemset ─────────────────────────────────────────────────────

_problemset_cache: Optional[tuple[float, list[dict]]] = None
_problemset_lock = asyncio.Lock()


async def load_problemset(force: bool = False) -> list[dict]:
    """
    Load and memoize the full problemset (~20MB upstream).

    A lock ensures concurrent tool calls share one in-flight request instead of
    stampeding the Codeforces rate limit.
    """
    global _problemset_cache

    loop = asyncio.get_running_loop()
    if not force and _problemset_cache:
        fetched_at, summaries = _problemset_cache
        if loop.time() - fetched_at < config.PROBLEMSET_TTL:
            return summaries

    async with _problemset_lock:
        if not force and _problemset_cache:
            fetched_at, summaries = _problemset_cache
            if loop.time() - fetched_at < config.PROBLEMSET_TTL:
                return summaries

        result = await call_api("problemset.problems", force=force, ttl=config.PROBLEMSET_TTL)
        summaries = normalize_problemset(result)
        _problemset_cache = (loop.time(), summaries)
        return summaries


def reset_problemset_cache() -> None:
    """Drop the memoized problemset. Used by the test suite."""
    global _problemset_cache
    _problemset_cache = None


async def search_problemset(query: str, limit: int = 10) -> dict:
    """Search the official problemset by id, title, tag or rating."""
    if not isinstance(query, str) or not query.strip():
        raise CodeforcesError("Search query must be a non-empty string.", code="INVALID_INPUT")

    summaries = await load_problemset()
    items = search_problems(summaries, query, _clamp(limit, 1, 50, 10))
    return {
        "query": query,
        "totalIndexed": len(summaries),
        "returned": len(items),
        "items": items,
        "source": "https://codeforces.com/api/problemset.problems",
        "fetchedAt": _now(),
    }


async def get_problem_metadata(native_id: str) -> dict:
    """Resolve one problem by `158A`, `158/A` or `158-A`."""
    normalized = normalize_problem_id(native_id).upper()
    if not normalized:
        raise CodeforcesError("Problem id must be a non-empty string.", code="INVALID_INPUT")

    summaries = await load_problemset()
    for summary in summaries:
        if summary["nativeId"].upper() == normalized:
            return {**summary, "fetchedAt": _now()}

    raise CodeforcesError(f'Codeforces problem "{native_id}" was not found.', code="NOT_FOUND")


async def list_problems_by_filter(
    tags: Optional[list[str]] = None,
    min_rating: Optional[int] = None,
    max_rating: Optional[int] = None,
    limit: int = 25,
) -> dict:
    """Filter the problemset by tag and rating range, most-solved first."""
    tags = tags or []
    wanted = [str(t).lower() for t in tags]
    low = min_rating if min_rating is not None else 0
    high = max_rating if max_rating is not None else 10_000

    summaries = await load_problemset()
    matched = []
    for problem in summaries:
        problem_tags = [str(t).lower() for t in problem["tags"]]
        if wanted and not all(tag in problem_tags for tag in wanted):
            continue
        rating = problem.get("rating")
        if rating is None:
            if min_rating is not None or max_rating is not None:
                continue
        elif not (low <= rating <= high):
            continue
        matched.append(problem)

    matched.sort(key=lambda p: -(p.get("solvedCount") or 0))
    items = matched[: _clamp(limit, 1, 100, 25)]

    return {
        "filters": {"tags": tags, "minRating": min_rating, "maxRating": max_rating},
        "totalIndexed": len(summaries),
        "matched": len(matched),
        "returned": len(items),
        "items": items,
        "fetchedAt": _now(),
    }


# ── Users ──────────────────────────────────────────────────────────


async def get_user_info(handles: list[str] | str) -> dict:
    """Profiles for 1-10 handles."""
    if isinstance(handles, str):
        raw = [h.strip() for h in handles.replace(",", ";").split(";")]
    else:
        raw = [str(h).strip() for h in handles]
    items = [h for h in raw if h]

    if not items:
        raise CodeforcesError("At least one handle is required.", code="INVALID_INPUT")
    if len(items) > 10:
        raise CodeforcesError("At most 10 handles can be requested at once.", code="INVALID_INPUT")
    for handle in items:
        assert_handle(handle)

    result = await call_api("user.info", {"handles": ";".join(items)})
    return {"users": [_compact_user(u) for u in result], "fetchedAt": _now()}


async def get_user_rating(handle: str, limit: int = 50) -> dict:
    """Contest rating history with per-contest deltas, newest first."""
    assert_handle(handle)
    result = await call_api("user.rating", {"handle": handle})

    history = []
    for entry in result:
        new_rating = entry.get("newRating")
        old_rating = entry.get("oldRating")
        tier = rating_tier(new_rating)
        history.append(
            {
                "contestId": entry.get("contestId"),
                "contestName": entry.get("contestName"),
                "rank": entry.get("rank"),
                "oldRating": old_rating,
                "newRating": new_rating,
                "ratingChange": (new_rating - old_rating)
                if new_rating is not None and old_rating is not None
                else None,
                "tier": tier["tier"] if tier else None,
                "date": _iso(entry.get("ratingUpdateTimeSeconds")),
            }
        )

    best = max(history, key=lambda h: h["newRating"] or 0, default=None)
    current = history[-1] if history else None
    with_delta = [h for h in history if h["ratingChange"] is not None]
    current_tier = rating_tier(current["newRating"]) if current else None

    return {
        "handle": handle,
        "totalContests": len(history),
        "currentRating": current["newRating"] if current else None,
        "currentTier": current_tier["tier"] if current_tier else None,
        "bestRating": (
            {"rating": best["newRating"], "contest": best["contestName"], "date": best["date"]}
            if best
            else None
        ),
        "biggestGain": max(with_delta, key=lambda h: h["ratingChange"], default=None),
        "biggestDrop": min(with_delta, key=lambda h: h["ratingChange"], default=None),
        "contests": list(reversed(history[-_clamp(limit, 1, 500, 50) :])),
        "profileUrl": f"https://codeforces.com/profile/{handle}",
        "fetchedAt": _now(),
    }


async def get_user_submissions(handle: str, from_index: int = 1, count: int = 25) -> dict:
    """Recent submissions for a handle, compacted for LLM context."""
    assert_handle(handle)
    result = await call_api(
        "user.status",
        {
            "handle": handle,
            "from": _clamp(from_index, 1, 1_000_000, 1),
            "count": _clamp(count, 1, 200, 25),
        },
    )
    return {
        "handle": handle,
        "returned": len(result),
        "submissions": [_compact_submission(s) for s in result],
        "fetchedAt": _now(),
    }


async def get_user_stats(handle: str, sample_size: int = 2000) -> dict:
    """Derived analytics over a user's submission history."""
    assert_handle(handle)
    result = await call_api(
        "user.status",
        {"handle": handle, "from": 1, "count": _clamp(sample_size, 100, 10_000, 2000)},
    )

    solved: set[str] = set()
    attempted: set[str] = set()
    verdicts: dict[str, int] = {}
    languages: dict[str, int] = {}
    tags: dict[str, int] = {}
    ratings: dict[int, int] = {}

    for submission in result:
        problem = submission.get("problem") or {}
        identity = problem.get("contestId") or problem.get("problemsetName")
        key = f"{identity}/{problem.get('index')}" if problem else None
        if key:
            attempted.add(key)

        verdict = submission.get("verdict") or "TESTING"
        verdicts[verdict] = verdicts.get(verdict, 0) + 1

        language = submission.get("programmingLanguage")
        if language:
            languages[language] = languages.get(language, 0) + 1

        if verdict == "OK" and key and key not in solved:
            solved.add(key)
            for tag in problem.get("tags") or []:
                tags[tag] = tags.get(tag, 0) + 1
            rating = problem.get("rating")
            if isinstance(rating, int):
                ratings[rating] = ratings.get(rating, 0) + 1

    def top(counter: dict, n: int) -> list[dict]:
        ordered = sorted(counter.items(), key=lambda kv: -kv[1])[:n]
        return [{"name": name, "count": count} for name, count in ordered]

    return {
        "handle": handle,
        "submissionsAnalyzed": len(result),
        "uniqueProblemsAttempted": len(attempted),
        "uniqueProblemsSolved": len(solved),
        "acceptanceRate": round(verdicts.get("OK", 0) / len(result) * 100, 1) if result else 0,
        "verdicts": verdicts,
        "topLanguages": top(languages, 5),
        "topTags": top(tags, 12),
        "solvedByRating": {str(k): ratings[k] for k in sorted(ratings)},
        "hardestSolvedRating": max(ratings) if ratings else None,
        "profileUrl": f"https://codeforces.com/profile/{handle}",
        "fetchedAt": _now(),
    }


async def compare_users(handles: list[str]) -> dict:
    """Side-by-side comparison of 2-5 handles, highest rated first."""
    if not isinstance(handles, list) or not (2 <= len(handles) <= 5):
        raise CodeforcesError("Provide between 2 and 5 handles to compare.", code="INVALID_INPUT")

    payload = await get_user_info(handles)
    ranked = sorted(payload["users"], key=lambda u: -(u.get("rating") or 0))
    return {
        "users": ranked,
        "highestRated": ranked[0]["handle"] if ranked else None,
        "fetchedAt": _now(),
    }


async def get_rated_users(
    active_only: bool = True, limit: int = 100, min_rating: Optional[int] = None
) -> dict:
    """
    Top rated users. The upstream list has hundreds of thousands of entries, so
    the result is ALWAYS capped to protect the model's context window.
    """
    cap = _clamp(limit, 1, 1000, 100)
    result = await call_api(
        "user.ratedList", {"activeOnly": "true" if active_only else "false"}, ttl=3600
    )
    filtered = (
        [u for u in result if (u.get("rating") or 0) >= min_rating] if min_rating else result
    )
    page = filtered[:cap]

    return {
        "activeOnly": active_only,
        "minRating": min_rating,
        "totalRatedUsers": len(result),
        "matched": len(filtered),
        "returned": len(page),
        "users": [_compact_user(u) for u in page],
        "fetchedAt": _now(),
    }


# ── Contests ───────────────────────────────────────────────────────


async def get_contest_list(
    gym: bool = False, phase: Optional[str] = None, limit: int = 25
) -> dict:
    """Contest list, optionally filtered by phase. Always capped."""
    result = await call_api("contest.list", {"gym": "true" if gym else None})
    wanted = phase.upper() if phase else None
    filtered = [c for c in result if c.get("phase") == wanted] if wanted else result
    page = filtered[: _clamp(limit, 1, 200, 25)]

    return {
        "gym": gym,
        "phase": wanted,
        "totalContests": len(result),
        "matched": len(filtered),
        "returned": len(page),
        "contests": [_compact_contest(c) for c in page],
        "fetchedAt": _now(),
    }


async def get_upcoming_contests(limit: int = 10) -> dict:
    """Next scheduled contests (phase BEFORE), soonest first."""
    result = await call_api("contest.list", ttl=300)
    upcoming = sorted(
        (c for c in result if c.get("phase") == "BEFORE"),
        key=lambda c: c.get("startTimeSeconds") or 0,
    )[: _clamp(limit, 1, 50, 10)]

    contests = []
    for contest in upcoming:
        relative = contest.get("relativeTimeSeconds")
        contests.append(
            {
                **_compact_contest(contest),
                "startsInHours": round(-relative / 3600, 1) if relative is not None else None,
            }
        )

    return {"returned": len(contests), "contests": contests, "fetchedAt": _now()}


async def get_contest_standings(
    contest_id: int,
    from_rank: int = 1,
    count: int = 20,
    handles: Optional[list[str]] = None,
    show_unofficial: bool = False,
) -> dict:
    """
    Standings for a contest.

    NOTE: anonymous callers may only request ``?contestId=<id>`` — Codeforces
    rejects from/count/handles outright — so the full standings are fetched once
    (and cached) and the window is applied locally.
    """
    if not isinstance(contest_id, int) or isinstance(contest_id, bool) or contest_id <= 0:
        raise CodeforcesError("contestId must be a positive integer.", code="INVALID_INPUT")

    handle_list = [h for h in (handles or []) if h]
    for handle in handle_list:
        assert_handle(handle)

    result = await call_api("contest.standings", {"contestId": contest_id}, ttl=600)
    wanted = {h.lower() for h in handle_list} if handle_list else None

    all_rows = []
    for row in result.get("rows") or []:
        party = row.get("party") or {}
        participant_type = party.get("participantType")
        if not show_unofficial and participant_type and participant_type != "CONTESTANT":
            continue
        if wanted and not any(
            str(m.get("handle", "")).lower() in wanted for m in party.get("members") or []
        ):
            continue
        all_rows.append(row)

    start = _clamp(from_rank, 1, 1_000_000, 1) - 1
    rows = all_rows[start : start + _clamp(count, 1, 200, 20)]

    return {
        "contest": _compact_contest(result.get("contest") or {}),
        "problems": [
            {
                "index": p.get("index"),
                "name": p.get("name"),
                "rating": p.get("rating"),
                "points": p.get("points"),
                "tags": p.get("tags") or [],
            }
            for p in result.get("problems") or []
        ],
        "totalRows": len(result.get("rows") or []),
        "matchedRows": len(all_rows),
        "from": start + 1,
        "returned": len(rows),
        "rows": [
            {
                "rank": row.get("rank"),
                "party": [m.get("handle") for m in (row.get("party") or {}).get("members") or []],
                "participantType": (row.get("party") or {}).get("participantType"),
                "points": row.get("points"),
                "penalty": row.get("penalty"),
                "successfulHacks": row.get("successfulHackCount", 0),
                "unsuccessfulHacks": row.get("unsuccessfulHackCount", 0),
                "problemResults": [
                    {
                        "points": pr.get("points"),
                        "rejectedAttempts": pr.get("rejectedAttemptCount", 0),
                        "type": pr.get("type"),
                        "bestSubmissionTimeSeconds": pr.get("bestSubmissionTimeSeconds"),
                    }
                    for pr in row.get("problemResults") or []
                ],
            }
            for row in rows
        ],
        "fetchedAt": _now(),
    }


async def get_contest_rating_changes(contest_id: int, limit: int = 50) -> dict:
    """Rating deltas applied after a rated contest."""
    if not isinstance(contest_id, int) or isinstance(contest_id, bool) or contest_id <= 0:
        raise CodeforcesError("contestId must be a positive integer.", code="INVALID_INPUT")

    result = await call_api("contest.ratingChanges", {"contestId": contest_id})
    page = result[: _clamp(limit, 1, 500, 50)]

    return {
        "contestId": contest_id,
        "totalParticipants": len(result),
        "returned": len(page),
        "changes": [
            {
                "handle": c.get("handle"),
                "rank": c.get("rank"),
                "oldRating": c.get("oldRating"),
                "newRating": c.get("newRating"),
                "ratingChange": (c.get("newRating") or 0) - (c.get("oldRating") or 0),
                "date": _iso(c.get("ratingUpdateTimeSeconds")),
            }
            for c in page
        ],
        "fetchedAt": _now(),
    }


async def get_contest_status(
    contest_id: int,
    handle: Optional[str] = None,
    from_index: int = 1,
    count: int = 25,
) -> dict:
    """Submissions made in a contest, optionally narrowed to one handle."""
    if not isinstance(contest_id, int) or isinstance(contest_id, bool) or contest_id <= 0:
        raise CodeforcesError("contestId must be a positive integer.", code="INVALID_INPUT")
    if handle:
        assert_handle(handle)

    result = await call_api(
        "contest.status",
        {
            "contestId": contest_id,
            "handle": handle or None,
            "from": _clamp(from_index, 1, 1_000_000, 1),
            "count": _clamp(count, 1, 200, 25),
        },
    )
    return {
        "contestId": contest_id,
        "handle": handle,
        "returned": len(result),
        "submissions": [_compact_submission(s) for s in result],
        "fetchedAt": _now(),
    }


async def get_recent_submissions(count: int = 25) -> dict:
    """Most recent submissions across the whole platform."""
    result = await call_api(
        "problemset.recentStatus", {"count": _clamp(count, 1, 1000, 25)}, ttl=60
    )
    return {
        "returned": len(result),
        "submissions": [_compact_submission(s) for s in result],
        "fetchedAt": _now(),
    }


# ── Capabilities & Health ──────────────────────────────────────────


def get_capabilities(transport: str = "local_stdio") -> dict:
    """Describe the supported, degraded and deliberately unsupported surface."""
    checked_at = _now()

    def op(name: str, status: str, tool: Optional[str] = None, reason: Optional[str] = None):
        return {
            "name": name,
            "status": status,
            "toolName": tool,
            "transport": transport,
            "auth": "none",
            "risk": "R0_public_read",
            "compliance": "official",
            "reason": reason,
            "checkedAt": checked_at,
        }

    return {
        "providerId": "codeforces-official-api",
        "providerVersion": ADAPTER_VERSION,
        "platform": "codeforces",
        "transport": transport,
        "readOnly": True,
        "operations": [
            op("searchProblems", "available", "search_problems"),
            op("listProblems", "available", "list_problems"),
            op(
                "fetchProblem",
                "degraded",
                "get_problem_metadata",
                "The official API exposes metadata only; full statements are not available.",
            ),
            op("fetchProfile", "available", "get_user_info"),
            op("listSubmissions", "available", "get_user_submissions"),
            op("fetchContests", "available", "get_contest_list"),
            op("fetchStandings", "available", "get_contest_standings"),
            op(
                "localRun",
                "unsupported",
                None,
                "This adapter never executes code; it is a read-only data provider.",
            ),
            op(
                "prepareSubmission",
                "unsupported",
                None,
                "The official API does not expose submission.",
            ),
            op(
                "commitSubmission",
                "unsupported",
                None,
                "The official API does not expose submission.",
            ),
        ],
        "languages": [],
        "source": {
            "kind": "official_api",
            "adapterId": "codeforces-official-api",
            "adapterVersion": ADAPTER_VERSION,
            "sourceUrl": "https://codeforces.com/api",
            "confidence": "authoritative",
            "fetchedAt": checked_at,
        },
    }


async def get_health(probe: bool = True) -> dict:
    """Probe the upstream API and report layered health."""
    probe_ok: Optional[bool] = None
    probe_error: Optional[dict] = None

    if probe:
        try:
            await call_api("contest.list", ttl=300)
            probe_ok = True
        except CodeforcesError as err:
            probe_ok = False
            probe_error = {"code": err.code, "message": err.message}

    snapshot = health_snapshot()
    code = (probe_error or {}).get("code") or (snapshot.get("lastError") or {}).get("code")

    if not code:
        overall = "healthy"
    elif code in {"NETWORK_TIMEOUT", "UPSTREAM"}:
        overall = "unavailable"
    else:
        overall = "degraded"

    return {
        "providerId": "codeforces-official-api",
        "platform": "codeforces",
        "checkedAt": _now(),
        "overall": overall,
        "layers": {
            "transport": "fail" if code == "NETWORK_TIMEOUT" else "pass",
            "protocol": "pass",
            "schema": "drift" if code == "SCHEMA_CHANGED" else ("unknown" if code else "pass"),
            "auth": "not_required",
            "upstream": (
                "timeout"
                if code == "NETWORK_TIMEOUT"
                else "rate_limited"
                if code == "RATE_LIMITED"
                else "fail"
                if code
                else "pass"
            ),
        },
        "liveProbe": probe_ok,
        "errorLayer": error_layer(code) if code else None,
        "latencyMs": snapshot.get("lastLatencyMs"),
        "cachedEntries": snapshot.get("cachedEntries"),
        "lastError": probe_error or snapshot.get("lastError"),
        "message": (
            "Codeforces upstream is degraded; retry a public read shortly."
            if code
            else "Codeforces official API provider is healthy."
        ),
    }
