"""
Structured logging for the Codeforces MCP Server.

CRITICAL: under STDIO transport, stdout carries the MCP JSON-RPC framing.
Every log record must therefore go to stderr, or the client will fail to
parse the protocol stream.
"""

import logging
import sys

_LOG_FORMAT = "[codeforces-mcp] %(levelname)s %(asctime)s %(name)s: %(message)s"


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure the root 'codeforces-mcp' logger to write to stderr."""
    root = logging.getLogger("codeforces-mcp")
    root.setLevel(level)

    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt="%H:%M:%S"))
        root.addHandler(handler)

    # Never let a stray handler write to stdout.
    root.propagate = False
    return root


logger = configure_logging()
