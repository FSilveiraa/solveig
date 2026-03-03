"""Registry for dynamically discovered plugin tools."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.plugins.utils import rescan_and_load_plugins

# tool.base.BaseTool imports plugins to load hooks and run them before execution
# which imports plugins.tools (this file), so this cannot import BaseTool
if TYPE_CHECKING:
    from solveig.schema.tool.base import BaseTool

T = TypeVar("T", bound="BaseTool")


@dataclass
class ToolRegistry:
    all: dict[str, type["BaseTool"]] = field(default_factory=dict)
    active: dict[str, type["BaseTool"]] = field(default_factory=dict)

    def clear(self) -> None:
        self.all.clear()
        self.active.clear()

    def register(self, tool_class: type[T]) -> type[T]:
        """Register a plugin tool. Used as a decorator."""
        self.all[tool_class.model_fields["title"].default] = tool_class
        return tool_class


PLUGIN_TOOLS = ToolRegistry()

# Module-level aliases — callers can import these directly instead of going through PLUGIN_TOOLS
tool = PLUGIN_TOOLS.register
clear_tools = PLUGIN_TOOLS.clear


async def load_and_filter_tools(config: SolveigConfig, interface: SolveigInterface):
    """Discover, load, and filter tool plugins, and update the UI."""
    PLUGIN_TOOLS.clear()

    await rescan_and_load_plugins(
        plugin_module_path="solveig.plugins.tools",
        interface=interface,
    )

    for plugin_name, tool_class in PLUGIN_TOOLS.all.items():
        if config.plugins and plugin_name in config.plugins:
            PLUGIN_TOOLS.active[plugin_name] = tool_class
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
