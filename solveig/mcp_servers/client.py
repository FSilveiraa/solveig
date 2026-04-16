"""MCP connection lifecycle management."""

from __future__ import annotations

import asyncio
import contextlib
import shlex
from typing import TYPE_CHECKING

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from solveig.config import MCPServerConfig
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

    def __init__(self, server_config: MCPServerConfig) -> None:
        self.server_config = server_config
        self.url = server_config.url
        self._server_name: str | None = None
        self.tools: list[type[BaseTool]] = []
        self._session: ClientSession | None = None
        self._task: asyncio.Task | None = None
        self._ready: asyncio.Event = asyncio.Event()
        self._done: asyncio.Event = asyncio.Event()
        self._error: BaseException | None = None

    @property
    def display_name(self) -> str:
        """User-configured name > server-reported name > URL."""
        return self.server_config.name or self._server_name or self.url

    @contextlib.asynccontextmanager
    async def _transport(self):  # type: ignore[return]
        """Yield (read, write) streams for the appropriate transport."""
        if self.url.startswith("stdio://"):
            parts = shlex.split(self.url[len("stdio://") :])
            params = StdioServerParameters(command=parts[0], args=parts[1:])
            async with stdio_client(params) as (read, write):
                yield read, write
        else:
            kwargs = {}
            if self.server_config.headers:
                kwargs["headers"] = self.server_config.headers
            async with streamable_http_client(self.url, **kwargs) as (read, write, _):
                yield read, write

    async def load_tools(self):
        available_tools = await self._session.list_tools()
        parsed_tools = [
            create_tool_class(tool, self._session)
            for tool in available_tools.tools
        ]
        self.tools = self.server_config.filter_tools(parsed_tools)

    async def _actually_open(self) -> None:
        """Background task: holds the transport + session context managers open."""
        try:
            async with self._transport() as (read, write):
                async with ClientSession(read, write) as session:
                    # initialize() is where streamable_http_client makes its first
                    # real TCP connection — do it here so failures are caught below.
                    init_result = await session.initialize()
                    self._server_name = init_result.serverInfo.name
                    self._session = session
                    await self.load_tools()
                    self._ready.set()
                    await self._done.wait()
        except BaseException as e:
            # Unwrap single-exception BaseExceptionGroups produced by anyio task
            # groups so callers see a plain, identifiable exception rather than a
            # BaseExceptionGroup that bypasses `except Exception` handlers.
            error: BaseException = e
            while isinstance(error, BaseExceptionGroup) and len(error.exceptions) == 1:
                error = error.exceptions[0]
            self._error = error
            self._ready.set()
            # Do NOT re-raise: "Task exception was never retrieved" warning if GC'd.

    async def open(self) -> None:
        self._task = asyncio.create_task(self._actually_open())
        await self._ready.wait()
        if self._error:
            raise self._error
        assert self._session is not None

    async def close(self) -> None:
        self._done.set()
        if self._task:
            with contextlib.suppress(BaseException):
                await self._task
        self._session = None
        self.tools = []


# Module-level registry: URL → connection
MCP_CONNECTIONS: dict[str, MCPConnection] = {}


def find_connection(identifier: str) -> MCPConnection | None:
    """Look up a connection by URL (exact) or display_name (fallback)."""
    if identifier in MCP_CONNECTIONS:
        return MCP_CONNECTIONS[identifier]
    for conn in MCP_CONNECTIONS.values():
        if conn.display_name == identifier:
            return conn
    return None


async def connect(
    server_config: MCPServerConfig,
    config: SolveigConfig,
    interface: SolveigInterface,
) -> MCPConnection | None:
    """Connect to an MCP server, register its tools, and rebuild the tools union.

    Displays success or error directly. Re-raises on failure so callers that
    need to react programmatically can, but callers that don't can suppress.
    """
    conn = MCPConnection(server_config)
    async with interface.with_animation(f"MCP connecting to {conn.display_name}"):
        try:
            await conn.open()
        except Exception as err:
            await interface.display_error(
                f"MCP '{conn.display_name}': {err}"
            )
            return None

    # Only reached on success — replace any existing connection at this URL
    if server_config.url in MCP_CONNECTIONS:
        await disconnect(server_config.url, config, interface)

    # Map the config URL to the connection, add the MCP tools
    MCP_CONNECTIONS[server_config.url] = conn
    MCP_TOOLS.extend(conn.tools)
    AVAILABLE_TOOLS.rebuild(config)
    tool_names = [t.model_fields["title"].default for t in conn.tools]
    # Display connection details and update MCP stats
    await interface.display_success(
        f"MCP '{conn.display_name}': connected ({len(conn.tools)} tools: {', '.join(tool_names)})"
    )
    await interface.update_stats(
        mcp_servers=[c.display_name for c in MCP_CONNECTIONS.values()]
    )
    return conn  # Already mapped, but still return


async def disconnect(
    url: str, config: SolveigConfig, interface: SolveigInterface
) -> None:
    """Disconnect from an MCP server by URL and rebuild the tools union."""
    conn = MCP_CONNECTIONS.pop(url, None)
    if conn is None:
        return
    for tool in conn.tools:
        if tool in MCP_TOOLS:
            MCP_TOOLS.remove(tool)
    await conn.close()
    AVAILABLE_TOOLS.rebuild(config)
    await interface.update_stats(
        mcp_servers=[c.display_name for c in MCP_CONNECTIONS.values()]
    )


async def connect_all(config: SolveigConfig, interface: SolveigInterface) -> None:
    """Connect to all servers listed in config.mcp_servers at startup."""
    for server_config in config.mcp_servers.values():
        await connect(server_config, config, interface)
