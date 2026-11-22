"""
Offline tests for the Python HTTP client and API layer.

The shared httpx client is swapped for one backed by ``httpx.MockTransport``,
so every upstream envelope (OK, FAILED, rate limit, 5xx, bad JSON, redirects)
is exercised without touching the network.
"""

import json
import types

import httpx
import pytest

from app.client import api, http
from app.config import config
from app.utils.errors import CodeforcesError

PROBLEMSET = {
    "problems": [
        {"contestId": 4, "index": "A", "name": "Watermelon", "rating": 800, "tags": ["math"]},
        {"contestId": 1700, "index": "C", "name": "Helping the Nature", "rating": 1500,
         "tags": ["dp", "greedy"]},
        {"contestId": 2000, "index": "Z", "name": "Unrated", "tags": ["dp"]},
    ],
    "problemStatistics": [
        {"contestId": 4, "index": "A", "solvedCount": 900000},
        {"contestId": 1700, "index": "C", "solvedCount": 12000},
        {"contestId": 2000, "index": "Z", "solvedCount": 5},
    ],
}


def ok(result):
    return httpx.Response(200, json={"status": "OK", "result": result})


def failed(comment, status=400):
    return httpx.Response(status, json={"status": "FAILED", "comment": comment})


class Upstream:
    """Routes requests by API method and records every call."""

    def __init__(self):
        self.routes = {}
        self.calls = []

    def on(self, method, *responses):
        self.routes[method] = list(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        self.calls.append(request)
        queue = self.routes.get(method)
        if not queue:
            return failed(f"no route for {method}", 500)
        response = queue[0] if len(queue) == 1 else queue.pop(0)
        return response(request) if callable(response) else response


@pytest.fixture
def upstream(monkeypatch):
    up = Upstream()
    http.clear_cache()
    api.reset_problemset_cache()
    monkeypatch.setattr(config, "MIN_REQUEST_INTERVAL", 0.0)

    async def no_sleep(_seconds):
        return None

    # Retries back off with asyncio.sleep; make them instant in tests only.
    monkeypatch.setattr(http, "asyncio", types.SimpleNamespace(sleep=no_sleep, Lock=http.asyncio.Lock))
    monkeypatch.setattr(
        http,
        "_client",
        httpx.AsyncClient(transport=httpx.MockTransport(up.handler), follow_redirects=True),
    )
    yield up
    http.clear_cache()
    api.reset_problemset_cache()


# ── HTTP envelope handling ─────────────────────────────────────────


async def test_unwraps_ok_result_and_sends_lang(upstream):
    upstream.on("user.info", ok([{"handle": "tourist", "rating": 3800}]))
    data = await api.get_user_info(["tourist"])
    assert data["users"][0]["handle"] == "tourist"
    assert data["users"][0]["tier"] == "legendary grandmaster"
    assert upstream.calls[0].url.params["lang"] == "en"
    assert upstream.calls[0].url.params["handles"] == "tourist"


async def test_failed_not_found_is_not_retried(upstream):
    upstream.on("user.rating", failed("handle: User with handle zzz not found"))
    with pytest.raises(CodeforcesError) as exc:
        await api.get_user_rating("zzz_not_real")
    assert exc.value.code == "NOT_FOUND"
    assert len(upstream.calls) == 1
    assert http.health_snapshot()["lastError"]["code"] == "NOT_FOUND"


async def test_call_limit_is_retried(upstream):
    upstream.on(
        "contest.list",
        failed("Call limit exceeded"),
        ok([{"id": 1, "name": "Round", "phase": "FINISHED"}]),
    )
    data = await api.get_contest_list(limit=5)
    assert data["returned"] == 1
    assert len(upstream.calls) == 2


async def test_server_errors_exhaust_retries(upstream):
    upstream.on("contest.list", httpx.Response(503, text="down"))
    with pytest.raises(CodeforcesError) as exc:
        await api.get_contest_list()
    assert exc.value.code == "UPSTREAM"
    assert len(upstream.calls) == config.MAX_RETRIES


async def test_invalid_json_is_schema_changed(upstream):
    upstream.on("contest.list", httpx.Response(200, text="<html>maintenance</html>"))
    with pytest.raises(CodeforcesError) as exc:
        await api.get_contest_list()
    assert exc.value.code == "SCHEMA_CHANGED"


async def test_missing_result_is_schema_changed(upstream):
    upstream.on("contest.list", httpx.Response(200, json={"status": "OK"}))
    with pytest.raises(CodeforcesError) as exc:
        await api.get_contest_list()
    assert exc.value.code == "SCHEMA_CHANGED"


async def test_redirect_off_codeforces_is_refused(upstream):
    def redirect(request):
        if request.url.host == "evil.example":
            return ok([])
        return httpx.Response(302, headers={"location": "https://evil.example/api/contest.list"})

    upstream.on("contest.list", redirect)
    with pytest.raises(CodeforcesError) as exc:
        await api.get_contest_list()
    assert exc.value.code == "UNEXPECTED_REDIRECT"


async def test_responses_are_cached(upstream):
    upstream.on("user.info", ok([{"handle": "tourist", "rating": 3800}]))
    await api.get_user_info(["tourist"])
    await api.get_user_info(["tourist"])
    assert len(upstream.calls) == 1


async def test_invalid_handle_never_hits_network(upstream):
    with pytest.raises(CodeforcesError) as exc:
        await api.get_user_rating("bad handle;")
    assert exc.value.code == "INVALID_HANDLE"
    assert upstream.calls == []


# ── Problemset ─────────────────────────────────────────────────────


async def test_problemset_is_loaded_once(upstream):
    upstream.on("problemset.problems", ok(PROBLEMSET))
    await api.search_problemset("watermelon")
    await api.get_problem_metadata("1700C")
    await api.list_problems_by_filter(tags=["dp"])
    assert len(upstream.calls) == 1


async def test_problem_metadata_and_not_found(upstream):
    upstream.on("problemset.problems", ok(PROBLEMSET))
    meta = await api.get_problem_metadata("4-a")
    assert meta["name"] == "Watermelon"
    assert meta["solvedCount"] == 900000
    with pytest.raises(CodeforcesError) as exc:
        await api.get_problem_metadata("999999Z")
    assert exc.value.code == "NOT_FOUND"


async def test_list_problems_excludes_unrated_when_bounded(upstream):
    upstream.on("problemset.problems", ok(PROBLEMSET))
    bounded = await api.list_problems_by_filter(tags=["dp"], min_rating=1000)
    assert [p["nativeId"] for p in bounded["items"]] == ["1700/C"]
    unbounded = await api.list_problems_by_filter(tags=["dp"])
    assert [p["nativeId"] for p in unbounded["items"]] == ["1700/C", "2000/Z"]


async def test_empty_search_is_rejected(upstream):
    with pytest.raises(CodeforcesError) as exc:
        await api.search_problemset("   ")
    assert exc.value.code == "INVALID_INPUT"


# ── Users ──────────────────────────────────────────────────────────


async def test_rating_history_summary(upstream):
    upstream.on(
        "user.rating",
        ok(
            [
                {"contestId": 1, "contestName": "A", "rank": 10, "oldRating": 0, "newRating": 1400,
                 "ratingUpdateTimeSeconds": 1_600_000_000},
                {"contestId": 2, "contestName": "B", "rank": 50, "oldRating": 1400, "newRating": 1300,
                 "ratingUpdateTimeSeconds": 1_600_100_000},
                {"contestId": 3, "contestName": "C", "rank": 5, "oldRating": 1300, "newRating": 1650,
                 "ratingUpdateTimeSeconds": 1_600_200_000},
            ]
        ),
    )
    data = await api.get_user_rating("someone", limit=2)
    assert data["currentRating"] == 1650
    assert data["currentTier"] == "expert"
    assert data["bestRating"]["contest"] == "C"
    assert data["biggestGain"]["ratingChange"] == 1400
    assert data["biggestDrop"]["ratingChange"] == -100
    assert [c["contestId"] for c in data["contests"]] == [3, 2]


async def test_user_stats(upstream):
    def sub(index, verdict, rating, tags, lang="C++"):
        return {
            "id": hash((index, verdict)),
            "problem": {"contestId": 1, "index": index, "name": index, "rating": rating, "tags": tags},
            "verdict": verdict,
            "programmingLanguage": lang,
        }

    upstream.on(
        "user.status",
        ok(
            [
                sub("A", "OK", 800, ["math"]),
                sub("A", "OK", 800, ["math"]),
                sub("B", "WRONG_ANSWER", 1200, ["dp"]),
                sub("B", "OK", 1200, ["dp"], "Python 3"),
            ]
        ),
    )
    stats = await api.get_user_stats("someone", sample_size=100)
    assert stats["uniqueProblemsSolved"] == 2
    assert stats["uniqueProblemsAttempted"] == 2
    assert stats["acceptanceRate"] == 75.0
    assert stats["verdicts"] == {"OK": 3, "WRONG_ANSWER": 1}
    assert stats["hardestSolvedRating"] == 1200
    assert stats["solvedByRating"] == {"800": 1, "1200": 1}
    assert stats["topLanguages"][0] == {"name": "C++", "count": 3}


async def test_compare_users_sorted_by_rating(upstream):
    upstream.on("user.info", ok([{"handle": "low", "rating": 1200}, {"handle": "high", "rating": 2500}]))
    data = await api.compare_users(["low", "high"])
    assert data["highestRated"] == "high"
    with pytest.raises(CodeforcesError):
        await api.compare_users(["only"])


async def test_rated_users_are_capped(upstream):
    upstream.on("user.ratedList", ok([{"handle": f"u{i:03d}", "rating": 4000 - i} for i in range(500)]))
    data = await api.get_rated_users(limit=10, min_rating=3800)
    assert data["returned"] == 10
    assert data["matched"] == 201
    assert data["totalRatedUsers"] == 500


# ── Contests ───────────────────────────────────────────────────────


async def test_standings_window_and_handle_filter(upstream):
    rows = [
        {"rank": i, "party": {"participantType": "CONTESTANT", "members": [{"handle": f"user{i}"}]},
         "points": 100 - i, "penalty": i, "problemResults": [{"points": 1, "type": "FINAL"}]}
        for i in range(1, 31)
    ]
    rows.append({"rank": 0, "party": {"participantType": "VIRTUAL", "members": [{"handle": "virt"}]}})
    upstream.on(
        "contest.standings",
        ok({"contest": {"id": 1700, "name": "Round", "phase": "FINISHED"},
            "problems": [{"index": "A", "name": "P"}], "rows": rows}),
    )

    page = await api.get_contest_standings(1700, from_rank=11, count=5)
    assert [r["rank"] for r in page["rows"]] == [11, 12, 13, 14, 15]
    assert page["matchedRows"] == 30
    assert page["totalRows"] == 31

    mine = await api.get_contest_standings(1700, handles=["USER7"])
    assert [r["party"] for r in mine["rows"]] == [["user7"]]

    everyone = await api.get_contest_standings(1700, count=200, show_unofficial=True)
    assert everyone["matchedRows"] == 31

    # The request must stay bare: anonymous standings reject every extra param.
    assert str(upstream.calls[0].url) == "https://codeforces.com/api/contest.standings?contestId=1700"
    assert len(upstream.calls) == 1


async def test_contest_id_validation(upstream):
    for bad in (0, -5, True):
        with pytest.raises(CodeforcesError) as exc:
            await api.get_contest_rating_changes(bad)
        assert exc.value.code == "INVALID_INPUT"
    assert upstream.calls == []


async def test_upcoming_contests_sorted(upstream):
    upstream.on(
        "contest.list",
        ok(
            [
                {"id": 3, "name": "Later", "phase": "BEFORE", "startTimeSeconds": 300, "relativeTimeSeconds": -7200},
                {"id": 2, "name": "Sooner", "phase": "BEFORE", "startTimeSeconds": 200, "relativeTimeSeconds": -3600},
                {"id": 1, "name": "Done", "phase": "FINISHED", "startTimeSeconds": 100},
            ]
        ),
    )
    data = await api.get_upcoming_contests()
    assert [c["id"] for c in data["contests"]] == [2, 3]
    assert data["contests"][0]["startsInHours"] == 1.0


async def test_submissions_are_compacted(upstream):
    raw = {
        "id": 42,
        "contestId": 4,
        "creationTimeSeconds": 1_700_000_000,
        "problem": {"contestId": 4, "index": "A", "name": "Watermelon", "rating": 800, "tags": ["math"]},
        "author": {"participantType": "CONTESTANT", "members": [{"handle": "tourist"}]},
        "programmingLanguage": "C++20",
        "verdict": "OK",
        "passedTestCount": 20,
        "timeConsumedMillis": 15,
        "memoryConsumedBytes": 0,
    }
    upstream.on("problemset.recentStatus", ok([raw]))
    data = await api.get_recent_submissions(count=1)
    sub = data["submissions"][0]
    assert sub["problem"] == "4/A"
    assert sub["handle"] == ["tourist"]
    assert sub["creationTime"].startswith("2023-11-14")
    assert json.dumps(sub)  # JSON-serializable


# ── Capabilities & health ──────────────────────────────────────────


def test_capabilities_are_read_only():
    caps = api.get_capabilities()
    assert caps["readOnly"] is True
    assert caps["providerId"] == "codeforces-official-api"
    statuses = {op["name"]: op["status"] for op in caps["operations"]}
    assert statuses["searchProblems"] == "available"
    assert statuses["commitSubmission"] == "unsupported"
    assert all(op["risk"] == "R0_public_read" for op in caps["operations"])


async def test_health_reports_probe_failure(upstream):
    upstream.on("contest.list", httpx.Response(503, text="down"))
    health = await api.get_health()
    assert health["liveProbe"] is False
    assert health["overall"] == "unavailable"
    assert health["errorLayer"] == "upstream"


async def test_health_healthy(upstream):
    upstream.on("contest.list", ok([]))
    health = await api.get_health()
    assert health["overall"] == "healthy"
    assert health["layers"]["upstream"] == "pass"
