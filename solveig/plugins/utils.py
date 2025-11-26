import importlib
import pkgutil

from solveig.interface import SolveigInterface


async def _discover_and_filter_plugins(
    interface: SolveigInterface,
    plugin_module_path: str,
) -> tuple[int, int]:
    """
    Generic utility to discover, filter, and display status for any type of plugin.
    Returns a dictionary of statistics.
    """
    succeeded, failed = (0, 0)
    try:
        module = importlib.import_module(plugin_module_path)
    except ImportError:
        await interface.display_error(f"Plugin discovery path not found: {plugin_module_path}")
    else:
        # Import all modules - don't log successes here, the dedicated plugin types do that during filtering
        for _, module_name, _ in pkgutil.iter_modules(module.__path__, f"{module.__name__}."):
            try:
                importlib.import_module(module_name)
                succeeded += 1
            except Exception as e:
                await interface.display_error(f"Failed to load plugin module {module_name}: {e}")
                failed += 1
    return (succeeded, failed)
