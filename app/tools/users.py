"""MCP tools for Codeforces user profiles and analytics."""

from typing import Any, Optional

from app.client import api
from app.mcp_server import mcp
from app.utils.errors import CodeforcesError
from app.utils.logger import logger


@mcp.tool()
async def get_user_info(handles: list[str]) -> dict[str, Any]:
    """Fetch structured profile data for 1-10 Codeforces handles.

    Returns rating, max rating, rank/tier, country, organization, contribution
    and registration date for each handle.

    Args:
        handles: One to ten Codeforces handles, e.g. ['tourist', 'Benq'].
    """
    logger.info("Tool 'get_user_info' called: handles=%s", handles)
    try:
        return await api.get_user_info(handles)
    except CodeforcesError as err:
        logger.error("get_user_info failed: %s", err.message)
        return err.to_dict()


@mcp.tool()
async def get_user_rating(handle: str, limit: int = 50) -> dict[str, Any]:
    """Return a user's contest rating history, newest first.

    Includes per-contest rating deltas, ranks, tier labels, best rating,
    biggest single gain and biggest single drop. Use for trend questions.

    Args:
        handle: Codeforces handle.
        limit: How many recent contests to return (default 50, max 500).
    """
    logger.info("Tool 'get_user_rating' called: handle=%r limit=%s", handle, limit)
    try:
        return await api.get_user_rating(handle, limit=limit)
    except CodeforcesError as err:
        logger.error("get_user_rating failed: %s", err.message)
        return err.to_dict()


@mcp.tool()
async def get_user_submissions(
    handle: str, from_index: int = 1, count: int = 25
) -> dict[str, Any]:
    """Return a user's recent submissions.

    Each submission is compacted to verdict, problem, language, runtime and
    memory. Raw Codeforces submission objects embed the entire problem and
    author team, so trimming them keeps the LLM context small.

    Args:
        handle: Codeforces handle.
        from_index: 1-based index of the first submission to return.
        count: How many submissions to return (default 25, max 200).
    """
    logger.info("Tool 'get_user_submissions' called: handle=%r count=%s", handle, count)
    try:
        return await api.get_user_submissions(handle, from_index=from_index, count=count)
    except CodeforcesError as err:
        logger.error("get_user_submissions failed: %s", err.message)
        return err.to_dict()


@mcp.tool()
async def get_user_stats(handle: str, sample_size: int = 2000) -> dict[str, Any]:
    """Compute derived performance analytics for a Codeforces user.

    Reports unique problems solved vs attempted, acceptance rate, verdict
    breakdown, favourite languages, strongest tags, the solved-by-rating
    distribution and the hardest problem solved. Answers 'how good is X' in a
    single call.

    Args:
        handle: Codeforces handle.
        sample_size: How many recent submissions to analyze (default 2000).
    """
    logger.info("Tool 'get_user_stats' called: handle=%r sample=%s", handle, sample_size)
    try:
        return await api.get_user_stats(handle, sample_size=sample_size)
    except CodeforcesError as err:
        logger.error("get_user_stats failed: %s", err.message)
        return err.to_dict()


@mcp.tool()
async def compare_users(handles: list[str]) -> dict[str, Any]:
    """Compare 2-5 Codeforces users side by side, highest rated first.

    Handy for 'who is stronger' or team-selection questions.

    Args:
        handles: Two to five Codeforces handles to compare.
    """
    logger.info("Tool 'compare_users' called: handles=%s", handles)
    try:
        return await api.compare_users(handles)
    except CodeforcesError as err:
        logger.error("compare_users failed: %s", err.message)
        return err.to_dict()


@mcp.tool()
async def get_rated_users(
    active_only: bool = True, min_rating: Optional[int] = None, limit: int = 100
) -> dict[str, Any]:
    """Return the top rated Codeforces users.

    The upstream list contains hundreds of thousands of entries, so results are
    ALWAYS capped to protect the model's context window.

    Args:
        active_only: Only include users active in the last month (default True).
        min_rating: Only include users at or above this rating.
        limit: Maximum users to return (default 100, max 1000).
    """
    logger.info("Tool 'get_rated_users' called: limit=%s min_rating=%s", limit, min_rating)
    try:
        return await api.get_rated_users(
            active_only=active_only, limit=limit, min_rating=min_rating
        )
    except CodeforcesError as err:
        logger.error("get_rated_users failed: %s", err.message)
        return err.to_dict()
