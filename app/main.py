"""
Codeforces MCP Server — HTTP entrypoint (Streamable HTTP transport).

Exposes the MCP server over HTTP for browser-based and remote AI clients
(Cursor, Claude web, Gemini, custom agents).

Usage:
    uvicorn app.main:app --host 0.0.0.0 --port 8000

The MCP endpoint is then available at:
    http://localhost:8000/mcp
"""

from app.mcp_server import mcp

# Importing these modules triggers @mcp.tool() registration. The imports look
# unused, but removing them would leave the server with zero tools.
import app.tools.problems   # noqa: F401,E402 — search_problems, get_problem_metadata, list_problems
import app.tools.users      # noqa: F401,E402 — get_user_info, get_user_rating, get_user_submissions,
                            #                   get_user_stats, compare_users, get_rated_users
import app.tools.contests   # noqa: F401,E402 — get_contest_list, get_upcoming_contests,
                            #                   get_contest_standings, get_contest_rating_changes,
                            #                   get_contest_status, get_recent_submissions
import app.tools.meta       # noqa: F401,E402 — get_capabilities, get_health

from app.config import config  # noqa: E402
from app.utils.logger import logger  # noqa: E402

for warning in config.validate():
    logger.warning(warning)

# Streamable HTTP ASGI application.
app = mcp.streamable_http_app()

logger.info("Codeforces MCP Server initialized (HTTP transport) — 17 tools registered")
