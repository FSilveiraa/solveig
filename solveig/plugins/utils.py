import importlib
import os
import pkgutil
import sys


def register_external_plugin_paths(paths: list[str]) -> None:
    """Fold external plugin dirs (`config.plugins.paths`) into the built-in
    packages' `__path__`, so the existing `pkgutil`-based scan discovers them with
    no extra machinery — external modules import as `solveig.plugins.tools.<name>`
    / `solveig.plugins.hooks.<name>`, so reload/unload and owner-name derivation
    all keep working. Convention: a plugin dir holds `tools/` and/or `hooks/`
    subdirs. Idempotent (skips already-registered dirs).

    Directory probing here uses `os.path` directly, not `Filesystem`: this is
    import-system plumbing (like `pkgutil`/`importlib` already are for the built-in
    scan), not a tool/assistant file operation, so it's outside Filesystem's remit."""
    # Local imports: utils is imported BY these packages, so importing them at
    # module level would cycle.
    import solveig.plugins.hooks as hooks_pkg
    import solveig.plugins.tools as tools_pkg

    for base in paths:
        base = os.path.expanduser(base)
        for subdir, package in (("tools", tools_pkg), ("hooks", hooks_pkg)):
            path = os.path.join(base, subdir)
            if os.path.isdir(path) and path not in package.__path__:
                package.__path__.append(path)


def rescan_and_load_plugins(plugin_module_path: str) -> tuple[int, int, list[str]]:
    """Synchronize in-memory plugins with the filesystem — idempotent and UI-free.

    Handles three cases: reloads modified modules, imports new ones, and unloads
    modules deleted from disk. Returns `(succeeded, failed, errors)`; discovery
    errors are returned as strings for the caller to surface (reporting is a
    separate step from discovery) rather than displayed here.
    """
    succeeded, failed = (0, 0)
    errors: list[str] = []

    # 1. Get Ground Truth: Discover all modules currently on the filesystem.
    on_disk_modules = set()
    try:
        module = importlib.import_module(plugin_module_path)
        for _, module_name, _ in pkgutil.iter_modules(
            module.__path__, f"{module.__name__}."
        ):
            on_disk_modules.add(module_name)
    except (ImportError, FileNotFoundError):
        return 0, 0, [f"Plugin discovery path not found: {plugin_module_path}"]

    # 2. Get Current State: Find all relevant modules already in memory.
    in_memory_modules = {
        name for name in sys.modules if name.startswith(f"{plugin_module_path}.")
    }

    # 3. Unload Deleted Plugins: Remove any modules from memory that are no longer on disk.
    modules_to_unload = in_memory_modules - on_disk_modules
    for module_name in modules_to_unload:
        del sys.modules[module_name]

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
            errors.append(f"Failed to load or reload plugin module {module_name}: {e}")
            failed += 1

    return succeeded, failed, errors
