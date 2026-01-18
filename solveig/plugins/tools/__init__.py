"""
Registry for dynamically discovered plugin tools.
"""

from typing import TYPE_CHECKING, TypeVar

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.plugins.utils import rescan_and_load_plugins

# The `if TYPE_CHECKING:` block is a standard Python trick to solve a circular import problem.
#
# The Problem:
# 1. This file needs to know what a `BaseTool` is for type hinting (`def register(cls: type[BaseTool])`).
# 2. However, the file that defines `BaseTool` (`solveig/schema/tool/base.py`) needs
#    to import from the `plugins` package to run hooks.
# 3. This creates a circular dependency: `plugins` -> `schema` -> `plugins`, which would crash the application.
#
# The Solution:
# - At RUNTIME, `TYPE_CHECKING` is `False`. Python skips this import, breaking the circle. The code
#   still works due to Python's dynamic nature ("duck typing").
# - During STATIC ANALYSIS (when you run `mypy`), `TYPE_CHECKING` is `True`. The import happens,
#   allowing `mypy` to correctly validate the types.
if TYPE_CHECKING:
    from solveig.schema.tool.base import BaseTool

# A TypeVar is used to tell the type checker that the decorator returns the exact same class
# that it received as an argument. This preserves the specific type (e.g., `TreeTool`)
# for better static analysis downstream.
T = TypeVar("T", bound=type["BaseTool"])


class PLUGIN_TOOLS:
    all: dict[str, type["BaseTool"]] = {}
    active: dict[str, type["BaseTool"]] = {}

    def __new__(cls, *args, **kwargs):
        raise TypeError("PLUGIN_TOOLS is a static registry and cannot be instantiated")

    @classmethod
    def register(cls, tool_class: T) -> T:
        """
        Registers a plugin tool. Used as a decorator.
        Adds the tool to the `all` hook plugins list.
        """
        cls.all[tool_class.__name__] = tool_class
        return tool_class

    @classmethod
    def clear(cls):
        """Clear all registered plugin tools (used by tests)."""
        cls.active.clear()
        cls.all.clear()  # TODO: may be necessary for true plugin reloading, but then we have to ensure that the reloading really... reloads classes from memory. AFAIK decorators don't get re-called from re-importing the module


async def load_and_filter_tools(config: SolveigConfig, interface: SolveigInterface):
    """
    Discover, load, and filter tool plugins, and update the UI.
    """
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


register_tool = PLUGIN_TOOLS.register

__all__ = [
    "PLUGIN_TOOLS",
    "register_tool",
    "load_and_filter_tools",
]
