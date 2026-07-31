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

The other half of tool execution - running the plugin `@before`/`@after` hooks
and rendering each `ToolResult` into a `ToolReturn` - is the `Hooks` capability
`build_tool_execution_capability()` in `solveig/agent.py`, attached to the
`Agent` alongside the toolset (not wrapped around it).
"""

from typing import Any

from pydantic_ai import FunctionToolset, RunContext, ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, CombinedToolset

from solveig.config import SolveigConfig
from solveig.context import SolveigContext
from solveig.mcp_servers import MCP_CONNECTIONS
from solveig.plugins.tools import PLUGIN_TOOLS
from solveig.tools import CORE_TOOLS
from solveig.tools.base import BaseTool


def _as_callable(tool: Any) -> Any:
    """Normalize a tool source to a plain pydantic-ai callable. `BaseTool`
    subclasses (all 9 core tools plus every current plugin tool, e.g. `tree`)
    are bridged via `.as_tool()`; a plain tool function passes through
    unchanged - kept for any future plugin author who writes one that way."""
    if isinstance(tool, type) and issubclass(tool, BaseTool):
        return tool.as_tool()
    return tool


def build_toolset(config: SolveigConfig) -> AbstractToolset:
    """Derive the active toolset by inspecting the tool stores: CORE_TOOLS,
    every discovered plugin tool, and every connected MCP server.

    Derived on demand rather than cached, because `build_agent()` already
    constructs a fresh Agent per turn — so a membership change (plugin rescan,
    MCP connect/disconnect) is picked up next turn on its own. Nothing has to
    announce that it changed, and no store has to know this module exists.

    MCP toolsets are wrapped in a live FilteredToolset that reads
    config.mcp[server_url].is_tool_allowed() on every call — the same reactive
    pattern as core tools.
    """
    mcp_toolsets: list[AbstractToolset] = []
    for server_url, conn in MCP_CONNECTIONS.items():
        ts = conn.toolset
        # Apply allow/block live — predicate reads config fresh each call.
        # When both lists are empty, is_tool_allowed returns True (no-op).

        def _mcp_active(
            ctx: RunContext[SolveigContext],
            td: ToolDefinition,
            url: str = server_url,
        ) -> bool:
            return ctx.deps.config.mcp[url].is_tool_allowed(td.name)

        ts = ts.filtered(_mcp_active)  # type: ignore[arg-type]
        mcp_toolsets.append(ts)

    # Every discovered plugin tool is included here; the FilteredToolset
    # below decides core-tool visibility live from `tools.<name>.enabled`
    # (plugin tools are enabled-by-default in the current schema).
    # Untyped on purpose: CORE_TOOLS/PLUGIN_TOOLS's specific callable
    # types don't unify into anything FunctionToolset's constructor (or
    # the .filtered() predicate's deps type below) accepts precisely -
    # same class of "no way to express a dynamic tool union to mypy"
    # noted elsewhere in this codebase.
    function_tools: list[Any] = [
        _as_callable(tool) for tool in (*CORE_TOOLS, *PLUGIN_TOOLS)
    ]

    if not function_tools and not mcp_toolsets:
        raise ValueError("No tools available: the tool list is empty.")

    def is_tool_active(
        ctx: RunContext[SolveigContext], tool_def: ToolDefinition
    ) -> bool:
        # Same rule the run_tool_and_hooks guard uses
        # (SolveigConfig.is_tool_enabled): a core tool is on iff its
        # `tools.<name>.enabled` flag is set; plugin tools are on by default.
        return ctx.deps.config.is_tool_enabled(tool_def.name)

    base = FunctionToolset(function_tools).filtered(is_tool_active)
    return CombinedToolset([base, *mcp_toolsets])


def tool_classes() -> dict[str, type[BaseTool]]:
    """Tool name -> class, for every `BaseTool`-based tool (core + plugin).

    Used by session replay to reconstruct a stored call's typed instance from
    its persisted args (`cls.model_validate(call.args_as_dict())`) - the only
    other place besides `rebuild()` that needs a full tool listing. A plain
    tool function (should a plugin author write one that way) has no entry
    here; replay falls back to a generic render for those.
    """
    classes: dict[str, type[BaseTool]] = {cls.tool_name(): cls for cls in CORE_TOOLS}
    for tool in PLUGIN_TOOLS:
        if isinstance(tool, type) and issubclass(tool, BaseTool):
            classes[tool.tool_name()] = tool
    return classes
