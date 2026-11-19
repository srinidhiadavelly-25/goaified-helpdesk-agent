"""
Small MCP client used by the LangGraph agent.

It starts the MCP server as a subprocess (stdio transport), opens a session,
calls one tool and returns the JSON result. A synchronous wrapper is provided
because Streamlit and LangGraph nodes here are synchronous.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src import config

SERVER_PARAMS = StdioServerParameters(
    command=sys.executable,                      # same Python / venv as the app
    args=["-m", "src.mcp_server"],
    cwd=str(config.PROJECT_ROOT),
    env={**os.environ},                          # passes DATABASE_URL etc.
)

ALLOWED_TOOLS = {"get_employee_profile", "get_leave_balance", "get_it_assets", "get_it_tickets"}


async def _call_tool_async(tool_name: str, arguments: dict) -> dict:
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            if result.structuredContent:
                data = result.structuredContent
                # FastMCP wraps non-object returns in {"result": ...}
                return data.get("result", data) if isinstance(data, dict) else {"data": data}
            text = "".join(getattr(c, "text", "") for c in result.content)
            return json.loads(text) if text else {}


async def _list_tools_async() -> list[str]:
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            return [t.name for t in tools.tools]


def call_tool(tool_name: str, arguments: dict) -> dict:
    """Synchronous helper: call one MCP tool and return its result as a dict."""
    if tool_name not in ALLOWED_TOOLS:  # allow-list: the agent can't invent tools
        return {"error": "TOOL_NOT_ALLOWED", "message": f"Tool {tool_name} is not permitted."}
    return asyncio.run(_call_tool_async(tool_name, arguments))


def list_tools() -> list[str]:
    return asyncio.run(_list_tools_async())
