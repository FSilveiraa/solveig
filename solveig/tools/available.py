"""Assembles the active tools
`AVAILABLE_TOOLS.rebuild(config)` only needs to be called after a genuine
change in tool *membership*: plugin modules (re)scanned (new tools may now
exist that didn't before) or an MCP server connecting/disconnecting (whole
new toolsets of previously-unknown tools appearing/disappearing). It does
NOT need to be called for `config.no_commands` or `config.plugins`
toggling - visibility for those is decided live, per step, by the
`FilteredToolset` wrapped around the base `FunctionToolset`, using whatever
`ctx.deps.config` says *right now*. This is deliberately built on
pydantic-ai's own `FilteredToolset` rather than a hand-rolled visibility
check, since "hide some already-known tools based on live config" is exactly
what it's for.

"""

from pydantic_ai import FunctionToolset, RunContext, ToolDefinition

from solveig.config import SolveigConfig
from solveig.context import SolveigContext
from solveig.tools import CORE_TOOLS, command
from solveig.tools.hook_runner import HookRunner
from solveig.tools.result import Finalizer

# MCP tools are appended here when an MCP server connects, removed on disconnect.
# Call AVAILABLE_TOOLS.rebuild(config) after mutating.
MCP_TOOLS: list = []


class AvailableTools:
    """Holds the currently active toolset, rebuilt from the current tool sources."""

    def __init__(self) -> None:
        self._toolset: Finalizer | None = None

    def rebuild(self, config: SolveigConfig) -> None:
        """Recompute the base toolset from CORE_TOOLS, every discovered plugin
        tool, and MCP_TOOLS. Only needed after tool *membership* actually
        changes - see the module docstring for why `no_commands`/`config.plugins`
        toggling doesn't need this."""
        # Local import: solveig.plugins.tools -> solveig.plugins (package init)
        # -> solveig.plugins.tools again during that same init - a module-level
        # import here would be circular.
        from solveig.plugins.tools import PLUGIN_TOOLS

        # Every discovered plugin tool is included here, not just the ones
        # config.plugins currently enables - the filter below decides
        # visibility live, per step, from config.
        all_tools = [*CORE_TOOLS, *PLUGIN_TOOLS.all.values(), *MCP_TOOLS]

        if not all_tools:
            raise ValueError("No tools available: the tool list is empty.")

        def is_tool_active(
            ctx: RunContext[SolveigContext], tool_def: ToolDefinition
        ) -> bool:
            active_config = ctx.deps.config
            if tool_def.name == command.__name__ and active_config.no_commands:
                return False
            owning_plugin = PLUGIN_TOOLS.owners.get(tool_def.name)
            if owning_plugin is not None and owning_plugin not in active_config.plugins:
                return False
            return True

        base = FunctionToolset(all_tools).filtered(is_tool_active)
        self._toolset = Finalizer(HookRunner(base))

    @property
    def toolset(self) -> Finalizer:
        assert self._toolset is not None, "Call rebuild() before accessing toolset"
        return self._toolset


AVAILABLE_TOOLS = AvailableTools()
