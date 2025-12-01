import importlib
import pkgutil
import sys

from solveig.interface import SolveigInterface


async def rescan_and_load_plugins(
    interface: SolveigInterface,
    plugin_module_path: str,
) -> tuple[int, int]:
    """
    Synchronizes in-memory plugins with the filesystem.

    This function handles three cases:
    1. Reloads modules that have been modified.
    2. Imports new modules that have been added.
    3. Unloads modules that have been deleted from the filesystem.
    """
    succeeded, failed = (0, 0)

    # 1. Get Ground Truth: Discover all modules currently on the filesystem.
    on_disk_modules = set()
    try:
        module = importlib.import_module(plugin_module_path)
        for _, module_name, _ in pkgutil.iter_modules(
            module.__path__, f"{module.__name__}."
        ):
            on_disk_modules.add(module_name)
    except (ImportError, FileNotFoundError):
        await interface.display_error(
            f"Plugin discovery path not found: {plugin_module_path}"
        )
        return 0, 0

    # 2. Get Current State: Find all relevant modules already in memory.
    in_memory_modules = {
        name
        for name in sys.modules
        if name.startswith(f"{plugin_module_path}.")
    }

    # 3. Unload Deleted Plugins: Remove any modules from memory that are no longer on disk.
    modules_to_unload = in_memory_modules - on_disk_modules
    for module_name in modules_to_unload:
        del sys.modules[module_name]
        # Optionally, log this action.
        # await interface.display_info(f"Unloaded deleted plugin: {module_name}")

    # 4. Load/Reload Plugins: Iterate through what's on disk and sync memory.
    for module_name in on_disk_modules:
        try:
            if module_name in in_memory_modules:
                # Module exists, so reload it to pick up changes
                importlib.reload(sys.modules[module_name])
            else:
                # New module, import it for the first time
                importlib.import_module(module_name)
            succeeded += 1
        except Exception as e:
            await interface.display_error(
                f"Failed to load or reload plugin module {module_name}: {e}"
            )
            failed += 1

    return succeeded, failed
