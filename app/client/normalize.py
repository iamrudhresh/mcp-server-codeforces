"""
Pure normalizers and search scoring — the Python mirror of `src/normalize.js`.

Everything here is synchronous and side-effect free so it can be unit-tested
without any network access.
"""

import re
from typing import Any, Optional

# ── Rating tiers ───────────────────────────────────────────────────

RANK_TIERS: list[tuple[float, str, str]] = [
    (1199, "newbie", "gray"),
    (1399, "pupil", "green"),
    (1599, "specialist", "cyan"),
    (1899, "expert", "blue"),
    (2099, "candidate master", "violet"),
    (2299, "master", "orange"),
    (2399, "international master", "orange"),
    (2599, "grandmaster", "red"),
    (2999, "international grandmaster", "red"),
    (float("inf"), "legendary grandmaster", "red"),
]


def rating_tier(rating: Optional[int]) -> Optional[dict[str, str]]:
    """Map a numeric rating to its Codeforces tier name and colour."""
    if rating is None or isinstance(rating, bool) or not isinstance(rating, (int, float)):
        return None
    for ceiling, tier, color in RANK_TIERS:
        if rating <= ceiling:
            return {"tier": tier, "color": color}
    return None


# ── Problem ids ────────────────────────────────────────────────────

_PROBLEM_ID_RE = re.compile(r"^(\d+)\s*(?:[/\-_]\s*)?([a-z][a-z0-9]*)$", re.IGNORECASE)


def normalize_problem_id(value: Any) -> str:
    """Canonicalize `158A`, `158/A`, `158-A`, `158 a` into `158/A`."""
    if not isinstance(value, str):
        return ""
    trimmed = value.strip()
    match = _PROBLEM_ID_RE.match(trimmed)
    if match:
        return f"{match.group(1)}/{match.group(2).upper()}"
    return trimmed


def slug(value: Any) -> str:
    """Lowercase and hyphenate a tag name."""
    return re.sub(r"\s+", "-", str(value).strip().lower())


# ── Problemset normalization ───────────────────────────────────────


def _statistics_key(entry: dict) -> str:
    contest_id = entry.get("contestId")
    index = entry.get("index")
    return str(index) if contest_id is None else f"{contest_id}/{index}"


def normalize_problemset(result: dict) -> list[dict]:
    """
    Flatten the `problemset.problems` envelope into compact problem summaries
    with a stable nativeId, canonical URL, tags and joined solved counts.
    """
    problems = (result or {}).get("problems") or []
    statistics = (result or {}).get("problemStatistics") or []
    solved_by_key = {_statistics_key(s): s.get("solvedCount") for s in statistics}

    summaries: list[dict] = []
    for problem in problems:
        contest_id = problem.get("contestId")
        index = problem.get("index")
        identity = str(contest_id) if contest_id is not None else problem.get("problemsetName")
        native_id = f"{identity}/{index}"

        if contest_id is not None:
            url = f"https://codeforces.com/problemset/problem/{contest_id}/{index}"
        else:
            name = problem.get("problemsetName") or "acmsguru"
            url = f"https://codeforces.com/problemsets/{name}"

        summaries.append(
            {
                "nativeId": native_id,
                "canonicalId": f"codeforces:{native_id}",
                "contestId": contest_id,
                "index": index,
                "name": problem.get("name"),
                "type": problem.get("type", "PROGRAMMING"),
                "rating": problem.get("rating"),
                "points": problem.get("points"),
                "tags": problem.get("tags") or [],
                "solvedCount": solved_by_key.get(_statistics_key(problem)),
                "url": url,
            }
        )
    return summaries


# ── Search scoring ─────────────────────────────────────────────────

_RANGE_RE = re.compile(r"^(\d{3,4})\s*[-–]\s*(\d{3,4})$")
_EXACT_RE = re.compile(r"^(\d{3,4})$")


def parse_rating_token(token: Any) -> Optional[dict[str, int]]:
    """
    Parse `1500`, `rating:1500` or `1200-1600` into an inclusive rating window.
    Returns None for anything that is not a plausible Codeforces rating.
    """
    normalized = re.sub(r"^rating:", "", str(token), flags=re.IGNORECASE).strip()

    match = _RANGE_RE.match(normalized)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        if low >= 800 and high <= 3500 and low <= high:
            return {"min": low, "max": high}
        return None

    match = _EXACT_RE.match(normalized)
    if match:
        rating = int(match.group(1))
        if 800 <= rating <= 3500 and rating % 100 == 0:
            return {"min": rating, "max": rating}
    return None


def _matches_rating(value: Optional[int], window: dict[str, int]) -> bool:
    return value is not None and window["min"] <= value <= window["max"]


def _match_single_token(summary: dict, native_id: str, title: str, token: str) -> int:
    token_id = normalize_problem_id(token).lower()
    if native_id == token_id:
        return 55
    if token in title:
        return 45
    if any(token in str(tag).lower() for tag in summary["tags"]):
        return 40
    window = parse_rating_token(token)
    if window:
        return 35 if _matches_rating(summary.get("rating"), window) else 0
    if len(token_id) >= 2 and token_id in native_id:
        return 30
    return 0


def match_score(summary: dict, query: str, id_query: str, tokens: list[str]) -> int:
    """
    Relevance score: exact id > id substring > exact title > title substring >
    tag > rating. Multi-word queries must match EVERY token (AND semantics).
    """
    native_id = summary["nativeId"].lower()
    if native_id == id_query:
        return 100

    # A bare rating such as "1500" must not be read as a partial id, otherwise
    # contest 1500's problems would outrank genuinely 1500-rated problems.
    window = parse_rating_token(query)
    if not window and len(id_query) >= 2 and id_query in native_id:
        return 80

    title = str(summary["name"] or "").lower()
    if title == query:
        return 70
    if query in title:
        return 60
    if any(query in str(tag).lower() for tag in summary["tags"]):
        return 40

    if window and _matches_rating(summary.get("rating"), window):
        return 35

    if len(tokens) > 1:
        total = 0
        for token in tokens:
            score = _match_single_token(summary, native_id, title, token)
            if score == 0:
                return 0
            total += score
        return min(55, round(total / len(tokens)))
    return 0


def search_problems(summaries: list[dict], query: str, limit: int) -> list[dict]:
    """Rank problem summaries against a free-text query and cap the results."""
    normalized_query = str(query).strip().lower()
    normalized_id_query = normalize_problem_id(query).lower()
    tokens = [t for t in normalized_query.split() if t]

    scored = [
        (match_score(s, normalized_query, normalized_id_query, tokens), s)
        for s in summaries
    ]
    matches = [(score, s) for score, s in scored if score > 0]

    matches.sort(key=lambda pair: (-pair[0], -(pair[1].get("solvedCount") or 0), pair[1]["nativeId"]))
    return [s for _, s in matches[:limit]]
