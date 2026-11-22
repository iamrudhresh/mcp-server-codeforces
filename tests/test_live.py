"""
Live integration tests against the real Codeforces API (Python runtime).

Skipped by default. Opt in with:  CF_LIVE=1 pytest tests/test_live.py -v
Mirrors test/smoke.js so both runtimes are checked against the same upstream.
"""

import os

import pytest

from app.client import api, http
from app.utils.errors import CodeforcesError

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("CF_LIVE") != "1", reason="set CF_LIVE=1 to hit the real API"),
]


@pytest.fixture(autouse=True)
async def fresh_client():
    # Each test gets its own event loop, so the shared client must be rebuilt.
    await http.close_client()
    yield
    await http.close_client()


async def test_search_dp_1500():
    data = await api.search_problemset("dp 1500", limit=5)
    assert data["items"] and all(p["rating"] == 1500 for p in data["items"])
    assert data["totalIndexed"] > 10000


async def test_search_bare_rating_returns_rated_problems():
    data = await api.search_problemset("1500", limit=10)
    assert data["items"] and all(p["rating"] == 1500 for p in data["items"])


async def test_problem_metadata_is_english():
    meta = await api.get_problem_metadata("4A")
    assert meta["nativeId"] == "4/A" and meta["name"] == "Watermelon"


async def test_list_problems():
    data = await api.list_problems_by_filter(tags=["dp"], min_rating=1200, max_rating=1400, limit=5)
    assert data["items"]
    assert all("dp" in p["tags"] and 1200 <= p["rating"] <= 1400 for p in data["items"])


async def test_users():
    info = await api.get_user_info(["tourist", "Benq"])
    assert len(info["users"]) == 2
    rating = await api.get_user_rating("tourist", limit=5)
    assert rating["totalContests"] > 50 and len(rating["contests"]) == 5
    subs = await api.get_user_submissions("tourist", count=5)
    assert len(subs["submissions"]) == 5
    stats = await api.get_user_stats("tourist", sample_size=200)
    assert stats["uniqueProblemsSolved"] > 0
    compare = await api.compare_users(["tourist", "Benq"])
    assert compare["users"][0]["rating"] >= compare["users"][1]["rating"]


async def test_rated_users():
    data = await api.get_rated_users(limit=10, min_rating=3000)
    assert len(data["users"]) == 10 and all(u["rating"] >= 3000 for u in data["users"])


async def test_contests():
    finished = await api.get_contest_list(phase="FINISHED", limit=5)
    assert all(c["phase"] == "FINISHED" for c in finished["contests"])
    upcoming = await api.get_upcoming_contests(limit=5)
    assert isinstance(upcoming["contests"], list)
    standings = await api.get_contest_standings(1700, count=5)
    assert standings["contest"]["id"] == 1700 and len(standings["rows"]) == 5
    changes = await api.get_contest_rating_changes(1700, limit=5)
    assert len(changes["changes"]) == 5
    status = await api.get_contest_status(1700, count=5)
    assert len(status["submissions"]) == 5
    recent = await api.get_recent_submissions(count=5)
    assert len(recent["submissions"]) == 5


async def test_health():
    assert (await api.get_health())["overall"] == "healthy"


async def test_unknown_handle_is_not_found():
    with pytest.raises(CodeforcesError) as exc:
        await api.get_user_rating("zzz_not_real_9f3a7x")
    assert exc.value.code == "NOT_FOUND"
