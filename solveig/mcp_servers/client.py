"""MCP connection lifecycle management.

Built on pydantic-ai's `MCPToolset` (itself built on FastMCP's `Client`),
which owns the real connection lifecycle - Solveig no longer hand-rolls a
background task holding a session open. `MCPToolset.__aenter__`/`__aexit__`
are reference-counted and reentrant: holding one external `__aenter__()`
here (in `connect()`) keeps the connection open for the whole session even
though `agent.run()` also enters/exits the same toolset once per turn - each
of those becomes a no-op nested increment/decrement as long as this
module's own hold is still outstanding.

`MCP_CONNECTIONS` is the single source of truth for connected servers. The
dict lives in `mcp_servers/__init__.py` so `tools/available.py` (which this
module imports to trigger rebuilds on connect/disconnect) can read the same
shared object at top level without a circular import: this module holds its
own reference, and only *other* modules import the dict from the package.
`AVAILABLE_TOOLS.rebuild()` derives the toolset list it needs
(`[c.toolset for c in MCP_CONNECTIONS.values()]`) from this dict directly
rather than a second list kept in sync by hand.
"""

from __future__ import annotations

import asyncio
import re
import shlex
from urllib.parse import urlparse

from fastmcp.client.transports import StdioTransport
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.toolsets import AbstractToolset

from solveig.config import MCPServerConfig, SolveigConfig
from solveig.context import SolveigContext, get_introspection_context
from solveig.interface import SolveigInterface
from solveig.mcp_servers import MCP_CONNECTIONS, MCPConnection
from solveig.subcommands.base import subcommand
from solveig.tools.available import AVAILABLE_TOOLS


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

    toolset: AbstractToolset = mcp_toolset.prefixed(tool_prefix)

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
        deps = SolveigContext(config=config, interface=interface)
        tools = await toolset.get_tools(get_introspection_context(deps))
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

    await interface.update_stats(
        f"MCP connected to {conn.server_name}",
        duration=2,
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
    server_name = conn.server_name
    await conn.toolset.__aexit__(None, None, None)
    AVAILABLE_TOOLS.rebuild(config)
    await interface.update_stats(
        mcp_servers=[c.display_name for c in MCP_CONNECTIONS.values()]
    )
    await interface.update_stats(
        f"MCP disconnected from {server_name}",
        duration=2,
    )


async def connect_all(config: SolveigConfig, interface: SolveigInterface) -> None:
    """Connect to all servers listed in config.mcp, concurrently."""
    await asyncio.gather(
        *(
            connect(server_config, config, interface)
            for server_config in config.mcp.values()
        )
    )


# ---------------------------------------------------------------------------
# Subcommands — the MCP client owns MCP connection management, so it declares
# the surface.
# ---------------------------------------------------------------------------


@subcommand("/mcp list", section="mcp")
async def mcp_list(
    config: SolveigConfig,
    interface: SolveigInterface,
) -> None:
    """List configured and connected MCP servers."""
    if not config.mcp and not MCP_CONNECTIONS:
        await interface.display_info(
            "No MCP servers configured. Use /mcp connect <url> to connect."
        )
        return

    lines: list[str] = []
    for conn in MCP_CONNECTIONS.values():
        name = conn.display_name
        tool_count = len(conn.tool_names)
        lines.append(f"● {name}  ({tool_count} tools)")
        for tool in conn.tool_names:
            lines.append(f"    {tool}")

    for url, cfg in config.mcp.items():
        if url not in MCP_CONNECTIONS:
            name = cfg.name or url
            lines.append(f"○ {name}  (configured, not connected)")

    await interface.display_text_box("\n".join(lines), title="MCP Servers")


@subcommand("/mcp connect", section="mcp", detail=True)
async def mcp_connect(
    config: SolveigConfig,
    interface: SolveigInterface,
    url: str,
) -> None:
    """Connect to an MCP server by URL."""
    url = url.strip()
    server_config = config.mcp.get(url, MCPServerConfig(url=url))
    await connect(server_config, config, interface)


@subcommand("/mcp disconnect", section="mcp", detail=True)
async def mcp_disconnect(
    config: SolveigConfig,
    interface: SolveigInterface,
    identifier: str,
) -> None:
    """Disconnect from an MCP server by URL or name."""
    identifier = identifier.strip()
    conn = find_connection(identifier)
    if conn is None:
        await interface.display_error(
            f"No connected MCP server matching '{identifier}'."
        )
        return
    await disconnect(conn.url, config, interface)
