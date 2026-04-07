"""MCP connection lifecycle management."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from solveig.interface import SolveigInterface
from solveig.schema.available import AVAILABLE_TOOLS, MCP_TOOLS
from solveig.schema.tool.base import BaseTool

from .adapter import create_tool_class

if TYPE_CHECKING:
    from solveig.config import SolveigConfig


class MCPConnection:
    """A persistent connection to a single MCP server.

    A background task holds the nested async context managers open.
    Callers await open() to establish the connection and call close() to tear it down.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        self.name: str = url  # replaced with serverInfo.name after initialize()
        self.tools: list[type[BaseTool]] = []
        self._session: ClientSession | None = None
        self._task: asyncio.Task | None = None
        self._ready: asyncio.Event = asyncio.Event()
        self._done: asyncio.Event = asyncio.Event()
        self._error: BaseException | None = None

    async def _run(self) -> None:
        """Background task: holds the HTTP + session context managers open."""
        try:
            async with streamable_http_client(self.url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    self._session = session
                    self._ready.set()
                    await self._done.wait()
        except BaseException as e:
            self._error = e
            self._ready.set()  # unblock open() if it's still waiting
            raise

    async def open(self) -> None:
        self._task = asyncio.create_task(self._run())
        await self._ready.wait()
        if self._error:
            raise self._error

        assert self._session is not None
        init_result = await self._session.initialize()
        self.name = init_result.serverInfo.name
        tools_result = await self._session.list_tools()
        self.tools = [create_tool_class(t, self._session) for t in tools_result.tools]

    async def close(self) -> None:
        self._done.set()
        if self._task:
            with contextlib.suppress(Exception):
                await self._task
        self._session = None
        self.tools = []


# Module-level registry: server name → connection
MCP_CONNECTIONS: dict[str, MCPConnection] = {}


async def connect(url: str, config: SolveigConfig, interface: SolveigInterface) -> MCPConnection:
    """Connect to an MCP server, register its tools, and rebuild the tools union."""
    conn = MCPConnection(url)
    await conn.open()

    # Replace any existing connection with the same name
    if conn.name in MCP_CONNECTIONS:
        await disconnect(conn.name, config, interface)

    MCP_CONNECTIONS[conn.name] = conn
    MCP_TOOLS.extend(conn.tools)
    AVAILABLE_TOOLS.rebuild(config)
    await interface.update_stats(mcp_servers=list(MCP_CONNECTIONS.keys()))
    return conn


async def disconnect(name: str, config: SolveigConfig, interface: SolveigInterface) -> None:
    """Disconnect from a named MCP server and rebuild the tools union."""
    conn = MCP_CONNECTIONS.pop(name, None)
    if conn is None:
        return
    for tool in conn.tools:
        if tool in MCP_TOOLS:
            MCP_TOOLS.remove(tool)
    await conn.close()
    AVAILABLE_TOOLS.rebuild(config)
    await interface.update_stats(mcp_servers=list(MCP_CONNECTIONS.keys()))


async def connect_all(config: SolveigConfig, interface: SolveigInterface) -> None:
    """Connect to all servers listed in config.mcp_servers at startup."""
    for url in config.mcp_servers:
        try:
            conn = await connect(url, config, interface)
            tool_names = [t.model_fields["title"].default for t in conn.tools]
            await interface.display_success(
                f"MCP '{conn.name}': connected ({len(conn.tools)} tools: {', '.join(tool_names)})"
            )
        except Exception as e:
            await interface.display_error(f"MCP connect failed for '{url}': {e}")
