"""
Offline unit tests for normalizers, search scoring and the error taxonomy.

These mirror `test/unit.js` so both runtimes are verified to behave identically.
Run with: pytest tests/ -v
"""

import pytest

from app.client.http import build_url, is_rate_limit_comment, is_valid_handle
from app.client.normalize import (
    match_score,
    normalize_problem_id,
    normalize_problemset,
    parse_rating_token,
    rating_tier,
    search_problems,
    slug,
)
from app.utils.errors import CodeforcesError, error_layer, is_retryable_code

FIXTURE = {
    "problems": [
        {
            "contestId": 158,
            "index": "A",
            "name": "Next Round",
            "type": "PROGRAMMING",
            "rating": 800,
            "tags": ["*special", "implementation"],
        },
        {
            "contestId": 4,
            "index": "A",
            "name": "Watermelon",
            "type": "PROGRAMMING",
            "rating": 800,
            "tags": ["brute force", "math"],
        },
        {
            "contestId": 1700,
            "index": "C",
            "name": "Helping the Nature",
            "type": "PROGRAMMING",
            "rating": 1500,
            "tags": ["dp", "greedy"],
        },
        {
            "problemsetName": "acmsguru",
            "index": "101",
            "name": "Domino",
            "type": "PROGRAMMING",
            "tags": ["graphs"],
        },
    ],
    "problemStatistics": [
        {"contestId": 158, "index": "A", "solvedCount": 500000},
        {"contestId": 4, "index": "A", "solvedCount": 900000},
        {"contestId": 1700, "index": "C", "solvedCount": 12000},
        {"index": "101", "solvedCount": 1500},
    ],
}


@pytest.fixture(scope="module")
def summaries() -> list[dict]:
    return normalize_problemset(FIXTURE)


# ── normalize_problemset ───────────────────────────────────────────


def test_normalizes_every_problem(summaries):
    assert len(summaries) == 4


def test_builds_native_and_canonical_ids(summaries):
    assert summaries[0]["nativeId"] == "158/A"
    assert summaries[0]["canonicalId"] == "codeforces:158/A"


def test_builds_problem_url(summaries):
    assert summaries[0]["url"] == "https://codeforces.com/problemset/problem/158/A"


def test_joins_solved_counts(summaries):
    assert summaries[0]["solvedCount"] == 500000
    assert summaries[3]["solvedCount"] == 1500


def test_carries_rating_and_tags(summaries):
    assert summaries[2]["rating"] == 1500
    assert summaries[2]["tags"] == ["dp", "greedy"]


def test_falls_back_to_problemset_name(summaries):
    assert summaries[3]["nativeId"] == "acmsguru/101"
    assert summaries[3]["url"] == "https://codeforces.com/problemsets/acmsguru"


def test_missing_rating_is_none(summaries):
    assert summaries[3]["rating"] is None


# ── normalize_problem_id ───────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("158A", "158/A"),
        ("158/A", "158/A"),
        ("158-A", "158/A"),
        ("158a", "158/A"),
        ("158 a", "158/A"),
        ("1700C1", "1700/C1"),
        ("  watermelon ", "watermelon"),
        (None, ""),
    ],
)
def test_normalize_problem_id(raw, expected):
    assert normalize_problem_id(raw) == expected


def test_slug():
    assert slug("Binary Search") == "binary-search"


# ── parse_rating_token ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "token,expected",
    [
        ("1500", {"min": 1500, "max": 1500}),
        ("rating:800", {"min": 800, "max": 800}),
        ("1200-1600", {"min": 1200, "max": 1600}),
        ("1550", None),
        ("100", None),
        ("1600-1200", None),
        ("greedy", None),
    ],
)
def test_parse_rating_token(token, expected):
    assert parse_rating_token(token) == expected


# ── search scoring ─────────────────────────────────────────────────


def test_match_scores(summaries):
    assert match_score(summaries[0], "158/a", "158/a", ["158/a"]) == 100
    assert match_score(summaries[1], "watermelon", "watermelon", ["watermelon"]) == 70
    assert match_score(summaries[2], "dp", "dp", ["dp"]) == 40
    assert match_score(summaries[2], "1500", "1500", ["1500"]) == 35
    assert match_score(summaries[2], "zzzz", "zzzz", ["zzzz"]) == 0


def _ids(items):
    return [p["nativeId"] for p in items]


def test_search_by_id_title_tag(summaries):
    assert _ids(search_problems(summaries, "158A", 5)) == ["158/A"]
    assert _ids(search_problems(summaries, "watermelon", 5)) == ["4/A"]
    assert _ids(search_problems(summaries, "greedy", 5)) == ["1700/C"]


def test_search_by_rating_and_tie_break(summaries):
    assert sorted(_ids(search_problems(summaries, "800", 5))) == ["158/A", "4/A"]
    assert search_problems(summaries, "800", 2)[0]["nativeId"] == "4/A"
    assert len(search_problems(summaries, "800", 1)) == 1


def test_multi_token_and_semantics(summaries):
    assert _ids(search_problems(summaries, "dp 1500", 5)) == ["1700/C"]
    assert search_problems(summaries, "dp 800", 5) == []
    assert search_problems(summaries, "nonexistentproblem", 5) == []


def test_rating_query_is_not_a_partial_id():
    fixture = {
        "problems": FIXTURE["problems"]
        + [{"contestId": 1500, "index": "A", "name": "Other", "rating": 2000, "tags": []}],
        "problemStatistics": FIXTURE["problemStatistics"],
    }
    items = normalize_problemset(fixture)
    assert _ids(search_problems(items, "1500", 5)) == ["1700/C"]
    assert search_problems(items, "1500A", 5)[0]["nativeId"] == "1500/A"
    assert search_problems(items, "dp 2000", 5) == []


# ── rating tiers ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "rating,tier",
    [
        (1100, "newbie"),
        (1300, "pupil"),
        (1600, "expert"),
        (2400, "grandmaster"),
        (3500, "legendary grandmaster"),
    ],
)
def test_rating_tier(rating, tier):
    assert rating_tier(rating)["tier"] == tier


def test_rating_tier_rejects_non_numbers():
    assert rating_tier(None) is None
    assert rating_tier(True) is None
    assert rating_tier("1500") is None


# ── handles, URLs, rate limits ─────────────────────────────────────


@pytest.mark.parametrize(
    "handle,valid",
    [
        ("tourist", True),
        ("a.b-c_d", True),
        ("abc", True),
        ("x" * 24, True),
        ("", False),
        ("ab", False),
        ("x" * 25, False),
        ("bad handle", False),
        ("a;b", False),
        (None, False),
    ],
)
def test_is_valid_handle(handle, valid):
    assert is_valid_handle(handle) is valid


def test_build_url_pins_english_and_skips_empty():
    url = build_url("user.status", {"handle": "tourist", "from": 1, "count": None, "x": ""})
    assert url == "https://codeforces.com/api/user.status?lang=en&handle=tourist&from=1"


def test_build_url_standings_is_bare():
    url = build_url("contest.standings", {"contestId": 1700, "from": 1, "count": 5})
    assert url == "https://codeforces.com/api/contest.standings?contestId=1700"


def test_rate_limit_comment():
    assert is_rate_limit_comment("Call limit exceeded")
    assert not is_rate_limit_comment("handle: User not found")
    assert not is_rate_limit_comment(None)


# ── error taxonomy ─────────────────────────────────────────────────


def test_error_layers():
    assert error_layer("NETWORK_TIMEOUT") == "transport"
    assert error_layer("RATE_LIMITED") == "upstream"
    assert error_layer("NOT_FOUND") == "upstream"
    assert error_layer("INVALID_INPUT") == "broker"
    assert is_retryable_code("RATE_LIMITED")
    assert not is_retryable_code("INVALID_HANDLE")


def test_error_to_dict():
    err = CodeforcesError("boom", code="UPSTREAM", status=503, retryable=True)
    assert isinstance(err, Exception)
    data = err.to_dict()
    assert data["status"] == "error"
    assert data["code"] == "UPSTREAM"
    assert data["layer"] == "upstream"
    assert data["retryable"] is True
