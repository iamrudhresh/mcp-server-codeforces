"""
MCP-level tests for the Python runtime.

1. In-process: every tool registers against FastMCP with a description and an
   object schema, and the tool set matches the Node runtime exactly.
2. End-to-end: boots ``run_server.py`` over STDIO as a real MCP client would
   and calls an offline tool through the protocol.
"""

import json
import re
import sys
from pathlib import Path

import pytest  # noqa: F401
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import app.main  # noqa: F401 — registers every tool
from app.mcp_server import mcp

ROOT = Path(__file__).resolve().parent.parent


def node_tool_names() -> list[str]:
    """Read TOOL_NAMES from src/tools.js so the two runtimes cannot drift."""
    source = (ROOT / "src" / "tools.js").read_text(encoding="utf-8")
    block = source.split("export const TOOL_NAMES = [", 1)[1].split("];", 1)[0]
    return re.findall(r'"([a-z_]+)"', block)


async def test_registers_the_same_tools_as_node():
    tools = await mcp.list_tools()
    names = sorted(t.name for t in tools)
    assert len(names) == 17
    assert names == sorted(node_tool_names())


async def test_every_tool_is_documented():
    for tool in await mcp.list_tools():
        assert tool.description and len(tool.description) > 40, tool.name
        assert tool.inputSchema["type"] == "object", tool.name
        assert not re.search(r"submit|run|execute|delete", tool.name)


async def test_offline_tool_call_in_process():
    result = await mcp.call_tool("get_capabilities", {})
    # FastMCP returns (content, structured) in recent SDKs, content list in older ones.
    content = result[0] if isinstance(result, tuple) else result
    payload = json.loads(content[0].text)
    assert payload["readOnly"] is True


async def test_validation_error_returns_structured_error():
    result = await mcp.call_tool("get_user_rating", {"handle": "bad handle;"})
    content = result[0] if isinstance(result, tuple) else result
    payload = json.loads(content[0].text)
    assert payload["status"] == "error"
    assert payload["code"] == "INVALID_HANDLE"


async def test_stdio_end_to_end():
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "run_server.py")], cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.serverInfo.name == "codeforces-mcp"

            listed = await session.list_tools()
            assert len(listed.tools) == 17

            caps = await session.call_tool("get_capabilities", {})
            assert not caps.isError
            assert json.loads(caps.content[0].text)["providerId"] == "codeforces-official-api"
