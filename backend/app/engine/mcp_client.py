"""
MCP client helpers — HTTP (SSE) and stdio transports.

Each call_tool_* function opens a fresh session per invocation.
For stdio servers this means spawning + tearing down the subprocess each call.
That's safe and simple for a demo. If latency matters in production, pool
sessions per server_id (add a ServerSessionPool here).
"""

import asyncio
import json
import logging
import os
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client

log = logging.getLogger(__name__)


async def list_tools_http(url: str) -> list[dict]:
    """Return the tool list from an HTTP/SSE MCP server."""
    async with sse_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.inputSchema,
                }
                for t in result.tools
            ]


async def call_tool_http(url: str, tool_name: str, arguments: dict[str, Any]) -> Any:
    """Call a single tool on an HTTP/SSE MCP server and return the content."""
    async with sse_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return _extract_content(result)


async def list_tools_stdio(
    command: str,
    args: list[str] | None = None,
    env_vars: dict[str, str] | None = None,
) -> list[dict]:
    """Return the tool list from a stdio MCP server."""
    params = _stdio_params(command, args, env_vars)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.inputSchema,
                }
                for t in result.tools
            ]


async def call_tool_stdio(
    command: str,
    args: list[str] | None = None,
    env_vars: dict[str, str] | None = None,
    tool_name: str = "",
    arguments: dict[str, Any] | None = None,
) -> Any:
    """Spawn an MCP stdio server, call one tool, return the content, then exit."""
    params = _stdio_params(command, args, env_vars)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments or {})
            return _extract_content(result)


# ---------------------------------------------------------------------------
# Unified dispatch
# ---------------------------------------------------------------------------


async def call_tool(
    *,
    transport: str,
    url: str | None = None,
    command: str | None = None,
    args: list[str] | None = None,
    env_vars: dict[str, str] | None = None,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> Any:
    if transport == "http":
        if not url:
            raise ValueError("url required for HTTP MCP transport")
        return await call_tool_http(url, tool_name, arguments or {})
    elif transport == "stdio":
        if not command:
            raise ValueError("command required for stdio MCP transport")
        return await call_tool_stdio(
            command=command,
            args=args,
            env_vars=env_vars,
            tool_name=tool_name,
            arguments=arguments or {},
        )
    else:
        raise ValueError(f"Unknown MCP transport: {transport!r}")


async def list_tools(
    *,
    transport: str,
    url: str | None = None,
    command: str | None = None,
    args: list[str] | None = None,
    env_vars: dict[str, str] | None = None,
) -> list[dict]:
    if transport == "http":
        if not url:
            raise ValueError("url required for HTTP MCP transport")
        return await list_tools_http(url)
    elif transport == "stdio":
        if not command:
            raise ValueError("command required for stdio MCP transport")
        return await list_tools_stdio(command=command, args=args, env_vars=env_vars)
    else:
        raise ValueError(f"Unknown MCP transport: {transport!r}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _stdio_params(
    command: str,
    args: list[str] | None,
    env_vars: dict[str, str] | None,
) -> StdioServerParameters:
    env = {**os.environ}
    if env_vars:
        env.update(env_vars)
    return StdioServerParameters(command=command, args=args or [], env=env)


def _extract_content(result) -> Any:
    """Pull the payload out of an MCP CallToolResult."""
    if not result.content:
        return None
    parts = []
    for block in result.content:
        if hasattr(block, "text"):
            # Try to parse JSON, fall back to raw string
            try:
                parts.append(json.loads(block.text))
            except (json.JSONDecodeError, TypeError):
                parts.append(block.text)
        elif hasattr(block, "data"):
            parts.append(block.data)
        else:
            parts.append(str(block))
    return parts[0] if len(parts) == 1 else parts
