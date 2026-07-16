"""MCP connection lifecycle management.

Built on pydantic-ai's `MCPToolset` (itself built on FastMCP's `Client`),
which owns the real connection lifecycle - Solveig no longer hand-rolls a
background task holding a session open. `MCPToolset.__aenter__`/`__aexit__`
are reference-counted and reentrant: holding one external `__aenter__()`
here (in `connect()`) keeps the connection open for the whole session even
though `agent.run()` also enters/exits the same toolset once per turn - each
of those becomes a no-op nested increment/decrement as long as this
module's own hold is still outstanding.

`MCP_CONNECTIONS` (not `tools/available.py`) is the single source of truth
for connected servers, for the same reason `PLUGIN_TOOLS` lives in
`plugins/tools/__init__.py`: the registry belongs next to the domain code
that mutates it, not the assembly code that reads it. `AVAILABLE_TOOLS.rebuild()`
derives the toolset list it needs (`[c.toolset for c in MCP_CONNECTIONS.values()]`)
from this dict directly rather than a second list kept in sync by hand.
"""

from __future__ import annotations

import asyncio
import re
import shlex
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from fastmcp.client.transports import StdioTransport
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.toolsets import AbstractToolset

from solveig.config import MCPServerConfig
from solveig.context import get_throwaway_context
from solveig.interface import SolveigInterface
from solveig.tools.available import AVAILABLE_TOOLS

if TYPE_CHECKING:
    from solveig.config import SolveigConfig


@dataclass
class MCPConnection:
    """A connected MCP server: its config plus the toolset used to reach it."""

    server_config: MCPServerConfig
    toolset: AbstractToolset
    """The filtered+prefixed toolset - entered/exited and placed in the
    combined agent toolset."""
    server_name: str | None = None
    """Server-reported name, captured once at connect time (server_info is
    only populated after __aenter__, and isn't worth keeping the raw
    MCPToolset around just to re-read later)."""
    tool_names: list[str] = field(default_factory=list)
    """Snapshot of (post-filter, post-prefix) tool names from connect time."""

    @property
    def url(self) -> str:
        return self.server_config.url

    @property
    def display_name(self) -> str:
        """User-configured name > server-reported name > URL."""
        return self.server_config.name or self.server_name or self.url


def _default_tool_prefix(url: str) -> str:
    """A model-friendly tool-name prefix derived from a server URL, used
    when the config gives no explicit `name`.

    `PrefixedToolset` joins this directly onto each tool name as
    `f'{prefix}_{name}'` - using the raw URL (e.g.
    `https://search.parallel.ai/mcp`) produces tool names like
    `https://search.parallel.ai/mcp_web_search`, which models reliably
    misparse (the `://` and `/` read as some kind of namespace syntax,
    observed causing a model to repeatedly guess at how to call the tool
    instead of just calling it). Derive a plain identifier instead: the
    URL's hostname for network transports, the command name for `stdio://`.
    """
    if url.startswith("stdio://"):
        command = shlex.split(url[len("stdio://") :])[0]
        base = command.rsplit("/", 1)[-1]
    else:
        base = urlparse(url).hostname or url
    return re.sub(r"[^a-zA-Z0-9_]+", "_", base).strip("_") or "mcp"


def _build_mcp_toolset(server_config: MCPServerConfig) -> MCPToolset:
    """Build the raw MCPToolset for a server config.

    FastMCP's own transport inference only recognizes bare `.py`/`.js`
    script paths and `http(s)://` URLs - not Solveig's `stdio://<command>`
    convention - so stdio needs an explicit StdioTransport built by hand.
    """
    url = server_config.url
    if url.startswith("stdio://"):
        parts = shlex.split(url[len("stdio://") :])
        transport = StdioTransport(command=parts[0], args=parts[1:])
        return MCPToolset(transport, init_timeout=server_config.timeout)
    return MCPToolset(
        url,
        headers=server_config.headers or None,
        init_timeout=server_config.timeout,
    )


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
    """Connect to an MCP server, register its tools, and rebuild the toolset.

    Displays success or error directly. Returns None on failure/cancellation
    rather than raising, since callers don't need to react programmatically.
    """
    # display_prefix is for human-facing messages below (readable name/URL);
    # tool_prefix is what actually gets joined onto each tool's name, so it
    # must be a plain identifier, not a URL - see _default_tool_prefix.
    display_prefix = server_config.name or server_config.url
    tool_prefix = server_config.name or _default_tool_prefix(server_config.url)
    mcp_toolset = _build_mcp_toolset(server_config)

    toolset: AbstractToolset = mcp_toolset
    if server_config.allowed_tools or server_config.blocked_tools:
        toolset = toolset.filtered(
            lambda ctx, tool_def: server_config.is_tool_allowed(tool_def.name)
        )
    toolset = toolset.prefixed(tool_prefix)

    conn = MCPConnection(server_config=server_config, toolset=toolset)

    try:
        async with interface.with_cancellable(
            toolset.__aenter__(), status=f"MCP connecting to {display_prefix}"
        ) as task:
            await task
    except asyncio.CancelledError:
        await interface.display_info(f"MCP connection to {display_prefix} cancelled")
        return None
    except Exception as err:
        await interface.display_error(f"MCP '{display_prefix}': {err}")
        return None

    conn.server_name = mcp_toolset.server_info.name

    try:
        tools = await toolset.get_tools(get_throwaway_context())
    except Exception as err:
        await toolset.__aexit__(None, None, None)
        await interface.display_error(
            f"MCP '{display_prefix}': failed to list tools: {err}"
        )
        return None

    conn.tool_names = list(tools.keys())

    # Only reached on success — replace any existing connection at this URL
    if server_config.url in MCP_CONNECTIONS:
        await disconnect(server_config.url, config, interface)

    MCP_CONNECTIONS[server_config.url] = conn
    AVAILABLE_TOOLS.rebuild(config)

    await interface.display_success(
        f"MCP '{conn.display_name}': connected "
        f"({len(conn.tool_names)} tools: {', '.join(conn.tool_names)})"
    )
    await interface.update_stats(
        mcp_servers=[c.display_name for c in MCP_CONNECTIONS.values()]
    )
    return conn


async def disconnect(
    url: str, config: SolveigConfig, interface: SolveigInterface
) -> None:
    """Disconnect from an MCP server by URL and rebuild the toolset."""
    conn = MCP_CONNECTIONS.pop(url, None)
    if conn is None:
        return
    await conn.toolset.__aexit__(None, None, None)
    AVAILABLE_TOOLS.rebuild(config)
    await interface.update_stats(
        mcp_servers=[c.display_name for c in MCP_CONNECTIONS.values()]
    )


async def connect_all(config: SolveigConfig, interface: SolveigInterface) -> None:
    """Connect to all servers listed in config.mcp_servers, concurrently."""
    await asyncio.gather(
        *(
            connect(server_config, config, interface)
            for server_config in config.mcp_servers.values()
        )
    )
