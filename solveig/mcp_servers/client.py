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
dict lives in `mcp_servers/__init__.py` so `tools/available.py` can read the
same shared object at top level without a circular import: this module holds
its own reference, and only *other* modules import the dict from the package.
`tools.available.build_toolset()` derives the toolset list it needs
(`[c.toolset for c in MCP_CONNECTIONS.values()]`) from this dict directly
rather than a second list kept in sync by hand.
"""

from __future__ import annotations

import asyncio
import shlex

from fastmcp.client.transports import StdioTransport
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.toolsets import AbstractToolset

from solveig.config import MCPServerConfig, SolveigConfig
from solveig.context import SolveigContext, get_introspection_context
from solveig.exceptions import UserCancel
from solveig.interface.base import Level, SolveigInterface
from solveig.mcp_servers import MCP_CONNECTIONS, MCPConnection
from solveig.subcommands import subcommand


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


async def connect(
    server_config: MCPServerConfig,
    config: SolveigConfig,
    interface: SolveigInterface,
) -> MCPConnection | None:
    """Connect to an MCP server and register its tools.

    Displays success or error directly. Returns None on failure/cancellation
    rather than raising, since callers don't need to react programmatically.

    The server's name is its identity throughout: the key it is stored under,
    the prefix joined onto every tool it exposes, and the word used to address
    it in a message or a subcommand. The server also reports a name of its own
    over the wire, which is deliberately ignored — a server that renamed itself
    mid-session would rename the tools the model had already been told about.
    """
    name = server_config.name
    toolset: AbstractToolset = _build_mcp_toolset(server_config).prefixed(name)

    conn = MCPConnection(server_config=server_config, toolset=toolset)

    try:
        async with interface.with_cancellable(status=f"MCP connecting to {name}"):
            await toolset.__aenter__()
    except UserCancel:
        await interface.print(f"MCP connection to {name} cancelled", level=Level.INFO)
        return None
    except Exception as err:
        await interface.print(f"MCP '{name}': {err}", level=Level.ERROR)
        return None

    try:
        deps = SolveigContext(config=config, interface=interface)
        tools = await toolset.get_tools(get_introspection_context(deps))
    except Exception as err:
        await toolset.__aexit__(None, None, None)
        await interface.print(
            f"MCP '{name}': failed to list tools: {err}", level=Level.ERROR
        )
        return None

    conn.tool_names = list(tools.keys())

    # Only reached on success — replace any existing connection under this name
    if name in MCP_CONNECTIONS:
        await disconnect(name, config, interface)

    MCP_CONNECTIONS[name] = conn

    await interface.set_status(f"MCP connected to {name}", duration=2)
    interface.refresh_stats()
    return conn


async def disconnect(
    name: str, config: SolveigConfig, interface: SolveigInterface
) -> None:
    """Disconnect from an MCP server by name."""
    conn = MCP_CONNECTIONS.pop(name, None)
    if conn is None:
        return
    await conn.toolset.__aexit__(None, None, None)
    interface.refresh_stats()
    await interface.set_status(f"MCP disconnected from {name}", duration=2)


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


@subcommand("/mcp", "/mcp list", section="mcp")
async def mcp_list(
    config: SolveigConfig,
    interface: SolveigInterface,
) -> None:
    """List configured and connected MCP servers."""
    if not config.mcp and not MCP_CONNECTIONS:
        await interface.print(
            "No MCP servers configured. Use /mcp connect <url> to connect.",
            level=Level.INFO,
        )
        return

    lines: list[str] = []
    for name, conn in MCP_CONNECTIONS.items():
        lines.append(f"● {name}  ({len(conn.tool_names)} tools)")
        for tool in conn.tool_names:
            lines.append(f"    {tool}")

    for name in config.mcp:
        if name not in MCP_CONNECTIONS:
            lines.append(f"○ {name}  (configured, not connected)")

    await interface.add_text_box("\n".join(lines), title="MCP Servers")


@subcommand("/mcp connect", section="mcp", detail=True)
async def mcp_connect(
    config: SolveigConfig,
    interface: SolveigInterface,
    target: str,
    name: str = "",
) -> None:
    """Connect to an MCP server, by configured name or by URL.

    A configured name connects that server as configured. Anything else is
    taken as a URL and connected ad hoc, under `name` if one was given and
    otherwise under an identifier derived from the URL.
    """
    target = target.strip()
    server_config = config.mcp.get(target) or MCPServerConfig.from_url(
        target, name.strip()
    )
    await connect(server_config, config, interface)


@subcommand("/mcp disconnect", section="mcp", detail=True)
async def mcp_disconnect(
    config: SolveigConfig,
    interface: SolveigInterface,
    name: str,
) -> None:
    """Disconnect from an MCP server by name."""
    name = name.strip()
    if name not in MCP_CONNECTIONS:
        await interface.print(
            f"No connected MCP server named '{name}'.", level=Level.ERROR
        )
        return
    await disconnect(name, config, interface)
