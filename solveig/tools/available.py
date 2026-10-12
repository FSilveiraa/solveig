"""Assembles the active toolset.

`build_toolset(config)` inspects the tool stores - CORE_TOOLS, PLUGIN_TOOLS and
MCP_CONNECTIONS - and returns a plain `CombinedToolset([FilteredToolset(
FunctionToolset), *mcp])`, no wrappers. Derived fresh per turn rather than
cached: `build_agent()` builds a new Agent each turn anyway, so a membership
change (plugin rescan, MCP connect/disconnect) is picked up on its own and
nothing has to announce it. `tools.<name>.enabled` toggling is likewise decided
live per step by the `FilteredToolset` from whatever `ctx.deps.config` says.
Built on pydantic-ai's own `FilteredToolset` rather than a hand-rolled
visibility check.

The other half of tool execution - running the plugin `@before_tool`/`@after_tool` hooks
and rendering each `ToolResult` into a `ToolReturn` - is the `Hooks` capability
`build_tool_execution_capability()` in `solveig/agent.py`, attached to the
`Agent` alongside the toolset (not wrapped around it).
"""

from typing import Any, Awaitable, Callable

from pydantic_ai import FunctionToolset, RunContext, ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, CombinedToolset
from pydantic_ai.messages import ToolReturn as PydanticAIToolReturn

from solveig.config import SolveigConfig
from solveig.mcp_servers.config import MCPServerConfig
from solveig.context import SolveigContext
from solveig.mcp_servers import MCP_CONNECTIONS
from solveig.tools.base import BaseTool


def build_toolset(config: SolveigConfig) -> AbstractToolset:
    """Derive the active toolset by inspecting the tool stores: CORE_TOOLS,
    every discovered plugin tool, and every connected MCP server.

    Derived on demand rather than cached, because `build_agent()` already
    constructs a fresh Agent per turn — so a membership change (plugin rescan,
    MCP connect/disconnect) is picked up next turn on its own. Nothing has to
    announce that it changed, and no store has to know this module exists.

    MCP toolsets are wrapped in a live FilteredToolset that reads
    config.mcp[server_name].is_tool_allowed() on every call — the same reactive
    pattern as core tools.
    """
    mcp_toolsets: list[AbstractToolset] = []
    for server_name, conn in MCP_CONNECTIONS.items():
        ts = conn.toolset
        # Apply allow/block live — predicate reads config fresh each call.
        # When both lists are empty, is_tool_allowed returns True (no-op).

        def _mcp_active(
            ctx: RunContext[SolveigContext],
            td: ToolDefinition,
            name: str = server_name,
            ad_hoc: MCPServerConfig = conn.server_config,
        ) -> bool:
            # Read config live so an edited allow/block list applies without a
            # reconnect — but fall back to the config the connection was opened
            # with, because `/mcp connect <url>` connects a server that no
            # config block names and `config.mcp[name]` would raise.
            return ctx.deps.config.mcp.servers.get(name, ad_hoc).is_tool_allowed(td.name)

        ts = ts.filtered(_mcp_active)  # type: ignore[arg-type]
        mcp_toolsets.append(ts)

    # Generate pydantic-ai callables for each tool model in core/plugin tools
    #  that is enabled in the config
    function_tools: list[Callable[..., Awaitable[PydanticAIToolReturn]]] = [
        tool_config.tool_class.as_pydantic_ai_tool(tool_config)
        for _tool_name, tool_config in config.tool_map.items()
        if tool_config.enabled
    ]

    if not function_tools and not mcp_toolsets:
        raise ValueError("No tools available: the tool list is empty.")

    def is_tool_active(
        ctx: RunContext[SolveigContext], tool_def: ToolDefinition
    ) -> bool:
        return ctx.deps.config.tool_map[tool_def.name].enabled

    base = FunctionToolset(function_tools).filtered(is_tool_active)
    return CombinedToolset([base, *mcp_toolsets])


def tool_classes(config: SolveigConfig) -> dict[str, type[BaseTool]]:
    """All available tool classes, including disabled tools, excluding MCP."""
    return {
        tool_name: tool_config.tool_class
        for tool_name, tool_config in config.tool_map
    }
