"""
FastMCP server instance for the Codeforces MCP Server.

All tool modules register against this single instance. FastMCP derives tool
schemas from Python type hints and docstrings, so the docstrings below the
``@mcp.tool()`` decorators are part of the public API contract.
"""

from mcp.server.fastmcp import FastMCP

from app import __version__
from app.config import config

mcp = FastMCP(
    "codeforces-mcp",
    host=config.HOST,
    port=config.PORT,
    instructions="""
    Codeforces MCP Server — read-only access to the official Codeforces API.

    Available capabilities:
    - Problemset:
      * Search problems by id ('158A'), title, tag ('dp', 'greedy') or rating ('1500', '1200-1600')
      * Fetch official metadata for a single problem
      * Build practice ladders by filtering on tags and a rating range
    - Users & Analytics:
      * Structured profiles for up to 10 handles at once
      * Full contest rating history with per-contest deltas, best rating, biggest gain/drop
      * Recent submission history, compacted for context efficiency
      * Derived performance analytics: solve counts, acceptance rate, verdict
        breakdown, favourite languages, strongest tags, solved-by-rating curve
      * Head-to-head comparison of 2-5 handles
      * The global rated leaderboard (always capped)
    - Contests:
      * List contests by phase, or just the next upcoming ones
      * Standings with problem list and a bounded window of ranked rows
      * Post-contest rating changes
      * Submissions within a contest, and live platform-wide activity

    Security: this server is strictly READ-ONLY. It never submits code, never
    executes code, and never accepts Codeforces credentials or cookies. Call
    get_capabilities to enumerate the supported surface, and get_health to
    diagnose failing calls.

    Note: the official Codeforces API exposes problem METADATA only — it does
    not serve full problem statements.
    """,
)

# Report this server's version (FastMCP otherwise reports the SDK version).
mcp._mcp_server.version = __version__
