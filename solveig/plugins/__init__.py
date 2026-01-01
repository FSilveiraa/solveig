"""
Plugin system for Solveig.
"""

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface

from .hooks import clear_hooks, load_and_filter_hooks
from .tools import PLUGIN_TOOLS, load_and_filter_tools


async def initialize_plugins(config: SolveigConfig, interface: SolveigInterface):
    """
    This is the single entry point for all plugin setup.
    It tells the other plugin sub-modules to initialize themselves.
    """
    async with interface.with_group("Plugins"):
        async with interface.with_group("Schema"):
            await load_and_filter_tools(config, interface)

        async with interface.with_group("Hooks"):
            await load_and_filter_hooks(config, interface)


def clear_plugins():
    clear_hooks()
    PLUGIN_TOOLS.clear()


__all__ = [
    "initialize_plugins",
    "clear_plugins",
]
