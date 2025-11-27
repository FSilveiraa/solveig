"""
Plugin system for Solveig.
"""

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface

from .hooks import load_and_filter_hooks, clear_hooks
from .schema import PLUGIN_REQUIREMENTS, load_and_filter_requirements


async def initialize_plugins(config: SolveigConfig, interface: SolveigInterface):
    """
    This is the single entry point for all plugin setup.
    It tells the other plugin sub-modules to initialize themselves.
    """
    async with interface.with_group("Plugins"):
        async with interface.with_group("Schema"):
            req_stats = await load_and_filter_requirements(config, interface)

        async with interface.with_group("Hooks"):
            hook_stats = await hooks.load_and_filter_hooks(config, interface)

        # Print the final summary.
        await interface.display_text(
            f"Plugin system ready: {req_stats['active']} requirements, {hook_stats['active']} hooks"
        )


def clear_plugins():
    clear_hooks()
    PLUGIN_REQUIREMENTS.clear()


__all__ = [
    "initialize_plugins",
    "clear_plugins",
]