"""
Single source of truth for which tools the LLM can use.

`AVAILABLE_TOOLS.rebuild(config)` must be called after any change to the active
tool set: plugin load/unload, MCP server connect/disconnect, or config mutations
that affect the tool set (e.g. toggling no_commands).
"""

from pydantic_ai.toolsets.function import FunctionToolset

from solveig.config import SolveigConfig
from solveig.plugins.tools import PLUGIN_TOOLS
from solveig.schema.hooks import HookRunner
from solveig.schema.result import Finalizer
from solveig.schema.tool import CORE_TOOLS, command

# MCP tools are appended here when an MCP server connects, removed on disconnect.
# Call AVAILABLE_TOOLS.rebuild(config) after mutating.
MCP_TOOLS: list = []


class AvailableTools:
    """Holds the currently active toolset, rebuilt from the current tool sources."""

    def __init__(self) -> None:
        self._toolset: Finalizer | None = None
        self._active_tools: list = []

    def rebuild(self, config: SolveigConfig) -> None:
        """Recompute the active toolset from CORE_TOOLS, active plugin tools, and MCP_TOOLS."""
        active = [*CORE_TOOLS, *PLUGIN_TOOLS.active.values(), *MCP_TOOLS]

        if config.no_commands and command in active:
            active.remove(command)

        if not active:
            raise ValueError("No tools available: the active tools list is empty.")

        self._active_tools = active
        self._toolset = Finalizer(HookRunner(FunctionToolset(active)))

    @property
    def toolset(self) -> Finalizer:
        assert self._toolset is not None, "Call rebuild() before accessing toolset"
        return self._toolset

    @property
    def active_tools(self) -> list:
        """The plain tool functions currently active - used to describe them in the system prompt."""
        return self._active_tools


AVAILABLE_TOOLS = AvailableTools()
