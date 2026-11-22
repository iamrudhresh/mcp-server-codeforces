"""MCP tools describing the provider itself: capabilities and health."""

from typing import Any

from app.client import api
from app.mcp_server import mcp
from app.utils.errors import CodeforcesError
from app.utils.logger import logger


@mcp.tool()
async def get_capabilities() -> dict[str, Any]:
    """Report which Codeforces operations this server supports.

    Lists available, degraded and deliberately unsupported operations. This
    adapter is strictly read-only: it never submits code, never executes code,
    and never accepts judge credentials. Call this first to discover the safe
    surface area.
    """
    logger.info("Tool 'get_capabilities' called")
    return api.get_capabilities("local_stdio")


@mcp.tool()
async def get_health(probe: bool = True) -> dict[str, Any]:
    """Probe the official Codeforces API and report provider health.

    Reports transport, protocol, schema, auth and upstream health, plus the
    last observed error and request latency. Use this to diagnose failing
    tool calls.

    Args:
        probe: Perform a live upstream probe (default True). Set False for a
            passive report based only on previously observed errors.
    """
    logger.info("Tool 'get_health' called: probe=%s", probe)
    try:
        return await api.get_health(probe=probe)
    except CodeforcesError as err:
        logger.error("get_health failed: %s", err.message)
        return err.to_dict()
