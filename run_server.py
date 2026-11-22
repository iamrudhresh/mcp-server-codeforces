"""
Codeforces MCP Server — Python entrypoint.

Supports both STDIO (Claude Desktop, Cline, local agents) and Streamable HTTP
(Cursor, browser clients, programmatic access).

Usage:
    # STDIO transport (default):
    python run_server.py

    # HTTP transport:
    python run_server.py --http
    python run_server.py --http --host 0.0.0.0 --port 8000

Configure in Claude Desktop:
    {
        "mcpServers": {
            "codeforces": {
                "command": "python",
                "args": ["/absolute/path/to/run_server.py"]
            }
        }
    }

Configure in Cursor (HTTP mode):
    {
        "mcpServers": {
            "codeforces": { "url": "http://localhost:8000/mcp" }
        }
    }
"""

import argparse
import asyncio
import os
import sys

# Make the project root importable regardless of the working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.mcp_server import mcp  # noqa: E402
from app.config import config  # noqa: E402
from app.client.http import close_client  # noqa: E402
from app.utils.logger import logger  # noqa: E402

# Importing these modules triggers @mcp.tool() registration.
import app.tools.problems   # noqa: F401,E402
import app.tools.users      # noqa: F401,E402
import app.tools.contests   # noqa: F401,E402
import app.tools.meta       # noqa: F401,E402


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Codeforces MCP Server — read-only access to the official "
            "Codeforces API for AI assistants."
        )
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run with the Streamable HTTP transport via Uvicorn (default: STDIO).",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=config.HOST,
        help=f"Bind address for HTTP mode (default: {config.HOST}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=config.PORT,
        help=f"Listen port for HTTP mode (default: {config.PORT}).",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload in HTTP mode (development only).",
    )
    return parser.parse_args()


def main() -> None:
    """Run the MCP server entrypoint."""
    args = parse_args()

    for warning in config.validate():
        logger.warning(warning)

    if args.http:
        logger.info("Starting Streamable HTTP transport on %s:%s", args.host, args.port)
        import uvicorn

        uvicorn.run(
            "app.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
    else:
        # IMPORTANT: never print to stdout here — it corrupts JSON-RPC framing.
        logger.info("Starting STDIO transport with 17 tools")
        try:
            mcp.run(transport="stdio")
        except KeyboardInterrupt:
            pass
        finally:
            # Best-effort close of the shared httpx client. The client belongs to
            # the loop FastMCP just tore down, so failures here are harmless.
            try:
                asyncio.run(close_client())
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    main()
