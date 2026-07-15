"""Registry for dynamically discovered plugin tools.

Unlike core tools (hand-listed in `CORE_TOOLS`, no marker needed - inclusion
in that list is the only "this is a tool" signal), plugin tools are found by
scanning modules at runtime (`rescan_and_load_plugins`), so there's no static
list anyone edits by hand. `@tool` here is that missing piece: a plugin
author's only job is to decorate their function so it self-registers into
`PLUGIN_TOOLS.all` - pure bookkeeping, no signature rewriting.

Indexed by tool (function) name, not plugin (file) name - pydantic-ai already
requires tool names to be globally unique, so this is free uniqueness rather
than an assumption. Keying by file name instead would silently collide
whenever one plugin file exports more than one tool (only the last
registration in that file would survive). `owners` tracks tool name -> plugin
name separately, for `config.plugins` enable/disable and reporting - a file
exporting several tools is one enable/disable unit, but each tool is its own
schema entry.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.plugins.utils import rescan_and_load_plugins
from solveig.tools.base import BaseTool

PluginTool = Callable[..., Awaitable[Any]] | type[BaseTool]


def _tool_name(fn: PluginTool) -> str:
    """The actual name a call is dispatched under: `.tool_name()` for a
    `BaseTool` subclass (e.g. `TreeTool` -> `"tree"`), `__name__` for a plain
    tool function - registry keys must match this, not a Python identifier
    (the same distinction `_tool_key` makes in `plugins/hooks/__init__.py`)."""
    if isinstance(fn, type) and issubclass(fn, BaseTool):
        return fn.tool_name()
    return fn.__name__


def _plugin_name(fn: PluginTool) -> str:
    """Derive a tool's owning plugin name from its module path (e.g. `solveig.plugins.tools.tree` -> `tree`)."""
    module = fn.__module__
    if ".tools." in module:
        return module.split(".tools.")[-1]
    return _tool_name(fn)


@dataclass
class ToolRegistry:
    all: dict[str, PluginTool] = field(default_factory=dict)
    owners: dict[str, str] = field(default_factory=dict)

    def clear(self) -> None:
        self.all.clear()
        self.owners.clear()

    def register(self, fn: PluginTool) -> PluginTool:
        """Register a plugin tool, indexed by its actual tool name."""
        name = _tool_name(fn)
        self.all[name] = fn
        self.owners[name] = _plugin_name(fn)
        return fn


PLUGIN_TOOLS = ToolRegistry()

# Module-level aliases — callers can import these directly instead of going through PLUGIN_TOOLS.
tool = PLUGIN_TOOLS.register
clear_tools = PLUGIN_TOOLS.clear


async def load_and_filter_tools(config: SolveigConfig, interface: SolveigInterface):
    """Discover, load, and filter tool plugins, and update the UI."""
    PLUGIN_TOOLS.clear()

    await rescan_and_load_plugins(
        plugin_module_path="solveig.plugins.tools",
        interface=interface,
    )

    reported_plugins: set[str] = set()
    for tool_name, _plugin_fn in PLUGIN_TOOLS.all.items():
        plugin_name = PLUGIN_TOOLS.owners[tool_name]
        if config.plugins and plugin_name in config.plugins:
            if plugin_name not in reported_plugins:
                await interface.display_success(f"'{plugin_name}': Loaded")
        else:
            if plugin_name not in reported_plugins:
                await interface.display_warning(
                    f"'{plugin_name}': Skipped (missing from config)"
                )
        reported_plugins.add(plugin_name)


__all__ = [
    "PLUGIN_TOOLS",
    "ToolRegistry",
    "tool",
    "clear_tools",
    "load_and_filter_tools",
]
