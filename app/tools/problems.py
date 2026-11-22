"""MCP tools for the Codeforces problemset."""

from typing import Any, Optional

from app.client import api
from app.mcp_server import mcp
from app.utils.errors import CodeforcesError
from app.utils.logger import logger


@mcp.tool()
async def search_problems(query: str, limit: int = 10) -> dict[str, Any]:
    """Search the official Codeforces problemset.

    Matches on problem id ('158A', '158/A'), title, tag ('dp', 'greedy',
    'binary search') or rating ('1500', '1200-1600'). Multi-word queries must
    match every token, so 'dp 1500' returns 1500-rated dynamic programming
    problems. Prefer this over scraping codeforces.com.

    Args:
        query: Free-text query: problem id, title, tag, or rating.
        limit: Maximum results to return (default 10, max 50).
    """
    logger.info("Tool 'search_problems' called: query=%r limit=%s", query, limit)
    try:
        return await api.search_problemset(query, limit=limit)
    except CodeforcesError as err:
        logger.error("search_problems failed: %s", err.message)
        return err.to_dict()


@mcp.tool()
async def get_problem_metadata(problem_id: str) -> dict[str, Any]:
    """Fetch official metadata for a single Codeforces problem.

    Accepts '158A', '158/A' or '158-A' and returns the name, rating, tags,
    solved count and canonical URL.

    NOTE: the Codeforces API does not expose full problem statements, so this
    returns metadata only.

    Args:
        problem_id: Problem id such as '158A', '158/A' or '158-A'.
    """
    logger.info("Tool 'get_problem_metadata' called: problem_id=%r", problem_id)
    try:
        return await api.get_problem_metadata(problem_id)
    except CodeforcesError as err:
        logger.error("get_problem_metadata failed: %s", err.message)
        return err.to_dict()


@mcp.tool()
async def list_problems(
    tags: Optional[list[str]] = None,
    min_rating: Optional[int] = None,
    max_rating: Optional[int] = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Browse the problemset with structured filters instead of a text query.

    Returns the most-solved problems that carry ALL of the given tags and fall
    within the rating range. Ideal for building a practice ladder.

    Args:
        tags: Tags that must ALL be present, e.g. ['dp', 'greedy'].
        min_rating: Minimum problem rating (inclusive).
        max_rating: Maximum problem rating (inclusive).
        limit: Maximum results to return (default 25, max 100).
    """
    logger.info(
        "Tool 'list_problems' called: tags=%s rating=%s-%s", tags, min_rating, max_rating
    )
    try:
        return await api.list_problems_by_filter(
            tags=tags, min_rating=min_rating, max_rating=max_rating, limit=limit
        )
    except CodeforcesError as err:
        logger.error("list_problems failed: %s", err.message)
        return err.to_dict()
