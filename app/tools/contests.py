"""MCP tools for Codeforces contests, standings and live activity."""

from typing import Any, Optional

from app.client import api
from app.mcp_server import mcp
from app.utils.errors import CodeforcesError
from app.utils.logger import logger


@mcp.tool()
async def get_contest_list(
    gym: bool = False, phase: Optional[str] = None, limit: int = 25
) -> dict[str, Any]:
    """List Codeforces contests with start time, duration, type and phase.

    Args:
        gym: List gym contests instead of regular ones (default False).
        phase: Only contests in this phase — BEFORE (upcoming), CODING
            (running), PENDING_SYSTEM_TEST, SYSTEM_TEST or FINISHED.
        limit: Maximum contests to return (default 25, max 200).
    """
    logger.info("Tool 'get_contest_list' called: gym=%s phase=%s", gym, phase)
    try:
        return await api.get_contest_list(gym=gym, phase=phase, limit=limit)
    except CodeforcesError as err:
        logger.error("get_contest_list failed: %s", err.message)
        return err.to_dict()


@mcp.tool()
async def get_upcoming_contests(limit: int = 10) -> dict[str, Any]:
    """Return the next scheduled Codeforces contests, soonest first.

    Includes how many hours away each contest starts. Use this for
    'when is the next contest' questions.

    Args:
        limit: Maximum contests to return (default 10, max 50).
    """
    logger.info("Tool 'get_upcoming_contests' called: limit=%s", limit)
    try:
        return await api.get_upcoming_contests(limit=limit)
    except CodeforcesError as err:
        logger.error("get_upcoming_contests failed: %s", err.message)
        return err.to_dict()


@mcp.tool()
async def get_contest_standings(
    contest_id: int,
    from_rank: int = 1,
    count: int = 20,
    handles: Optional[list[str]] = None,
    show_unofficial: bool = False,
) -> dict[str, Any]:
    """Fetch the standings table for a Codeforces contest.

    Returns contest metadata, the problem list, and a bounded window of ranked
    rows with points, penalty, hacks and per-problem results. Pass 'handles' to
    look up specific competitors instead of the top of the table.

    Args:
        contest_id: Numeric contest id, e.g. 1700.
        from_rank: 1-based rank to start the window from.
        count: How many rows to return (default 20, max 200).
        handles: Only return rows for these handles.
        show_unofficial: Keep non-CONTESTANT rows if present (default False).
            Anonymous Codeforces access only serves the official table, so
            unofficial/virtual rows are normally absent.
    """
    logger.info("Tool 'get_contest_standings' called: contest_id=%s", contest_id)
    try:
        return await api.get_contest_standings(
            contest_id,
            from_rank=from_rank,
            count=count,
            handles=handles,
            show_unofficial=show_unofficial,
        )
    except CodeforcesError as err:
        logger.error("get_contest_standings failed: %s", err.message)
        return err.to_dict()


@mcp.tool()
async def get_contest_rating_changes(contest_id: int, limit: int = 50) -> dict[str, Any]:
    """Return the rating deltas applied after a rated Codeforces contest.

    Reports handle, rank, old rating, new rating and the computed change. Only
    available once the contest has actually been rated.

    Args:
        contest_id: Numeric contest id, e.g. 1700.
        limit: Maximum participants to return (default 50, max 500).
    """
    logger.info("Tool 'get_contest_rating_changes' called: contest_id=%s", contest_id)
    try:
        return await api.get_contest_rating_changes(contest_id, limit=limit)
    except CodeforcesError as err:
        logger.error("get_contest_rating_changes failed: %s", err.message)
        return err.to_dict()


@mcp.tool()
async def get_contest_status(
    contest_id: int,
    handle: Optional[str] = None,
    from_index: int = 1,
    count: int = 25,
) -> dict[str, Any]:
    """Return submissions made in a specific Codeforces contest.

    Optionally narrowed to a single handle. Useful for reviewing what a
    competitor submitted and which verdicts they received.

    Args:
        contest_id: Numeric contest id, e.g. 1700.
        handle: Only this participant's submissions.
        from_index: 1-based start index.
        count: How many submissions to return (default 25, max 200).
    """
    logger.info("Tool 'get_contest_status' called: contest_id=%s handle=%r", contest_id, handle)
    try:
        return await api.get_contest_status(
            contest_id, handle=handle, from_index=from_index, count=count
        )
    except CodeforcesError as err:
        logger.error("get_contest_status failed: %s", err.message)
        return err.to_dict()


@mcp.tool()
async def get_recent_submissions(count: int = 25) -> dict[str, Any]:
    """Return the most recent submissions across the whole Codeforces platform.

    Compacted to verdict, problem, language and runtime. Useful for sampling
    live activity.

    Args:
        count: How many submissions to return (default 25, max 1000).
    """
    logger.info("Tool 'get_recent_submissions' called: count=%s", count)
    try:
        return await api.get_recent_submissions(count=count)
    except CodeforcesError as err:
        logger.error("get_recent_submissions failed: %s", err.message)
        return err.to_dict()
