"""Registry for dynamically discovered plugin tools."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.plugins.utils import rescan_and_load_plugins
from solveig.schema.tool import tool as _tool

PluginTool = Callable[..., Awaitable[Any]]


def _plugin_name(fn: PluginTool) -> str:
    """Derive a tool's owning plugin name from its module path (e.g. `solveig.plugins.tools.tree` -> `tree`)."""
    module = fn.__module__
    if ".tools." in module:
        return module.split(".tools.")[-1]
    return fn.__name__


@dataclass
class ToolRegistry:
    all: dict[str, PluginTool] = field(default_factory=dict)
    active: dict[str, PluginTool] = field(default_factory=dict)

    def clear(self) -> None:
        self.all.clear()
        self.active.clear()

    def register(self, fn: PluginTool) -> PluginTool:
        """Register a plugin tool - applies `@tool`'s pydantic-ai wrapping, then indexes the result by plugin name."""
        wrapped = _tool(fn)
        self.all[_plugin_name(wrapped)] = wrapped
        return wrapped


PLUGIN_TOOLS = ToolRegistry()

# Module-level aliases — callers can import these directly instead of going through PLUGIN_TOOLS.
# Named `tool` (not `plugin_tool`) so plugin authors use the exact same decorator name as core
# tools do - no collision in practice, since a plugin module imports this one, not `schema.tool`.
tool = PLUGIN_TOOLS.register
clear_tools = PLUGIN_TOOLS.clear


async def load_and_filter_tools(config: SolveigConfig, interface: SolveigInterface):
    """Discover, load, and filter tool plugins, and update the UI."""
    PLUGIN_TOOLS.clear()

    await rescan_and_load_plugins(
        plugin_module_path="solveig.plugins.tools",
        interface=interface,
    )

    for plugin_name, plugin_fn in PLUGIN_TOOLS.all.items():
        if config.plugins and plugin_name in config.plugins:
            PLUGIN_TOOLS.active[plugin_name] = plugin_fn
            await interface.display_success(f"'{plugin_name}': Loaded")
        else:
            await interface.display_warning(
                f"'{plugin_name}': Skipped (missing from config)"
            )


__all__ = [
    "PLUGIN_TOOLS",
    "ToolRegistry",
    "tool",
    "clear_tools",
    "load_and_filter_tools",
]
