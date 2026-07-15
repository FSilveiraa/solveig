"""
Plugin system for Solveig.
"""

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface

from .hooks import after, before, clear_hooks, load_and_filter_hooks
from .tools import clear_tools, load_and_filter_tools, tool


async def initialize_plugins(config: SolveigConfig, interface: SolveigInterface):
    """
    This is the single entry point for all plugin setup.
    It tells the other plugin sub-modules to initialize themselves.
    """
    async with interface.with_group("Plugins") as plugins_group:
        async with plugins_group.with_group("Tools") as tools_group:
            await load_and_filter_tools(config, tools_group)

        async with plugins_group.with_group("Hooks") as hooks_group:
            await load_and_filter_hooks(config, hooks_group)


def clear_plugins():
    clear_hooks()
    clear_tools()


__all__ = [
    "initialize_plugins",
    "clear_plugins",
    "tool",
    "before",
    "after",
]
