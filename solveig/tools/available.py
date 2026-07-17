"""Assembles the active toolset.

`AVAILABLE_TOOLS` holds a plain `CombinedToolset([FilteredToolset(FunctionToolset),
*mcp])` - no wrappers. `rebuild(config)` is only needed after a genuine change in
tool *membership* (plugin rescan, MCP connect/disconnect);
`config.no_commands`/`config.plugins` toggling is decided live per step by the
`FilteredToolset`, using whatever `ctx.deps.config` says right now, so it needs no
rebuild. Built on pydantic-ai's own `FilteredToolset` rather than a hand-rolled
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
from solveig.mcp_servers.connections import MCP_CONNECTIONS
from solveig.plugins.tools import PLUGIN_TOOLS
from solveig.tools import CORE_TOOLS, CommandTool
from solveig.tools.base import BaseTool


def _as_callable(tool: Any) -> Any:
    """Normalize a tool source to a plain pydantic-ai callable. `BaseTool`
    subclasses (all 9 core tools plus every current plugin tool, e.g. `tree`)
    are bridged via `.as_tool()`; a plain tool function passes through
    unchanged - kept for any future plugin author who writes one that way."""
    if isinstance(tool, type) and issubclass(tool, BaseTool):
        return tool.as_tool()
    return tool


class AvailableTools:
    """Holds the currently active toolset, rebuilt from the current tool sources.

    The toolset is a plain `CombinedToolset([FilteredToolset(FunctionToolset),
    *mcp])` - no `ToolResult`-rendering or hook-running wrappers. Rendering
    (`ToolResult` -> `ToolReturn`) and the `@before`/`@after` plugin hooks are
    handled by the native tool-execute `Hooks` capability built in
    `solveig/agent.py` and attached to the `Agent`, not by wrapping the
    toolset.
    """

    def __init__(self) -> None:
        self._toolset: AbstractToolset | None = None

    def rebuild(self, config: SolveigConfig) -> None:
        """Recompute the base toolset from CORE_TOOLS, every discovered plugin
        tool, and every connected MCP server's toolset. Only needed after tool
        *membership* actually changes - see the module docstring for why
        `no_commands`/`config.plugins` toggling doesn't need this."""
        mcp_toolsets = [conn.toolset for conn in MCP_CONNECTIONS.values()]

        # Every discovered plugin tool is included here, not just the ones
        # config.plugins currently enables - the filter below decides
        # visibility live, per step, from config.
        # Untyped on purpose: CORE_TOOLS/PLUGIN_TOOLS.all's specific callable
        # types don't unify into anything FunctionToolset's constructor (or
        # the .filtered() predicate's deps type below) accepts precisely -
        # same class of "no way to express a dynamic tool union to mypy"
        # noted elsewhere in this codebase.
        function_tools: list[Any] = [
            _as_callable(tool) for tool in (*CORE_TOOLS, *PLUGIN_TOOLS.all.values())
        ]

        if not function_tools and not mcp_toolsets:
            raise ValueError("No tools available: the tool list is empty.")

        def is_tool_active(
            ctx: RunContext[SolveigContext], tool_def: ToolDefinition
        ) -> bool:
            active_config = ctx.deps.config
            if tool_def.name == CommandTool.tool_name() and active_config.no_commands:
                return False
            owning_plugin = PLUGIN_TOOLS.owners.get(tool_def.name)
            if owning_plugin is not None and owning_plugin not in active_config.plugins:
                return False
            return True

        base = FunctionToolset(function_tools).filtered(is_tool_active)
        self._toolset = CombinedToolset([base, *mcp_toolsets])

    @property
    def toolset(self) -> AbstractToolset:
        assert self._toolset is not None, "Call rebuild() before accessing toolset"
        return self._toolset


AVAILABLE_TOOLS = AvailableTools()


def tool_classes() -> dict[str, type[BaseTool]]:
    """Tool name -> class, for every `BaseTool`-based tool (core + plugin).

    Used by session replay to reconstruct a stored call's typed instance from
    its persisted args (`cls.model_validate(call.args_as_dict())`) - the only
    other place besides `rebuild()` that needs a full tool listing. A plain
    tool function (should a plugin author write one that way) has no entry
    here; replay falls back to a generic render for those.
    """
    classes: dict[str, type[BaseTool]] = {cls.tool_name(): cls for cls in CORE_TOOLS}
    for tool in PLUGIN_TOOLS.all.values():
        if isinstance(tool, type) and issubclass(tool, BaseTool):
            classes[tool.tool_name()] = tool
    return classes
