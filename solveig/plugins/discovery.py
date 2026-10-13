"""Finding plugins, and saying what was found.

`discover_plugins(plugins_config)` imports whatever is on disk and fills the
plugin sections of that config: `@tool` types its own entry while its module is
imported, and the scan removes the type of an entry whose file is gone. It is
UI-free and synchronous, so it can run wherever the plugin set has to be settled.
`report_plugins(config.plugins, interface, scan)` renders the outcome in the
Plugins dialog, taking the scan's result rather than re-reading a module global.

NOTE: this is a real module rather than the package `__init__`, which is empty.
An `__init__` runs whenever anything under it is imported, so re-exporting here
would put `plugins.tools` in front of `plugins.hooks` for every importer —
including `orchestration`, which `plugins.tools` imports back for `@tool`.
"""
import importlib
import os
import pkgutil
import sys
import warnings
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field

from solveig.interface.base import Level, SolveigInterface

from .config import PluginsConfig
from .hooks import clear_hooks

#: The one package the scan walks. External dirs are folded into its `__path__`,
#: so a bundled and an external plugin are indistinguishable from here on.
PLUGIN_PACKAGE = "solveig.plugins.library"


@dataclass
class ScanResult:
    """What a scan produced: the modules that failed to import, and the
    declarations it refused.

    Returned to the caller rather than parked in a module global. A scan and the
    report that renders it happen in the same call now, so the errors have
    somewhere to go at the time they exist — and nobody has to remember that a
    module-level store is holding the previous scan's worth.

    `errors` are modules that failed to import. `collisions` are refused
    declarations - a plugin claiming a trigger another store already holds -
    which arrive as warnings from inside the import, the only channel available
    there. They are kept apart: a refused trigger is not a failure to load, and
    rendering it as one misreports a working plugin.
    """

    errors: list[str] = field(default_factory=list)
    collisions: list[str] = field(default_factory=list)


#: Fired once per scan, after the registries are refilled. Plain callables, so
#: this module needs to know nothing about its subscribers - the doorbell
#: pattern `UserMessageQueue.on_change` already uses.

# TODO: fully unused, config should be SSOT, review+remove
#: Batched BY CONSTRUCTION: the notification lives on the scan, not on each
#: registration, because a scan is the only thing that changes the plugin set.
#: Firing per registration would make each subscriber's work quadratic - one
#: full `model_rebuild` per hook over a growing field set, measured at 3.4s for
#: 200 hooks - and the registry could not stop a subscriber holding it wrong.
ON_SCANNED: list[Callable[[], None]] = []

PLUGIN_TARGETS: ContextVar[PluginsConfig | None] = ContextVar("plugin_scan_targets", default=None)


def rescan_and_load_plugins(
        plugins_config: PluginsConfig,
        plugin_module_path: str = "solveig.plugins.library"
) -> tuple[int, int, list[str], set[str] | None]:
    # 1. Add external plugin dirs to the process context so the scan can find them
    import solveig.plugins.library as library

    for base in plugins_config.paths:
        path = os.path.expanduser(base)
        if os.path.isdir(path) and path not in library.__path__:
            library.__path__.append(path)

    succeeded, failed = (0, 0)
    errors: list[str] = []

    # 2. Find all modules currently on the filesystem.
    on_disk_modules = set()
    try:
        module = importlib.import_module(plugin_module_path)
        for _, module_name, _ in pkgutil.iter_modules(
            module.__path__, f"{module.__name__}."
        ):
            on_disk_modules.add(module_name)
    except (ImportError, FileNotFoundError):
        # Return the found paths as None to differentiate "path does not exit"
        #  from "nothing was found inside this path"
        return 0, 0, [f"Plugin discovery path not found: {plugin_module_path}"], None

    # 3. Find all relevant modules already in memory.
    in_memory_modules = {
        name for name in sys.modules
        if name.startswith(f"{plugin_module_path}.")
    }

    # 4. Remove any modules from memory that are no longer on disk.
    modules_to_unload = in_memory_modules - on_disk_modules
    for module_name in modules_to_unload:
        del sys.modules[module_name]

    # 5. Iterate through what's on disk and sync memory.
    #  What these imports declare lands on `TARGETS`, for as long as they run.
    token = PLUGIN_TARGETS.set(plugins_config)
    try:
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
    finally:
        PLUGIN_TARGETS.reset(token)

    return succeeded, failed, errors, on_disk_modules



def discover_plugins(plugins_config: PluginsConfig) -> ScanResult:
    """Load every plugin into the registries it declares into — idempotent and
    UI-free. Folds the external dirs in `paths` into the library package first,
    then scans it once. Returns a `ScanResult` for the caller to surface (via
    `report_plugins`); kept reporting-free so the caller can decide when the
    interface is ready to draw.

    ONE scan, not one per surface. A plugin declares tools, hooks and
    subcommands with decorators, and a decorator does not care where the file
    sits — so scanning per surface only meant a plugin wanting two of them had
    to be two files, imported by two passes and cleared by two calls.

    Every registry is emptied before the scan, never inside a loader: the scan
    re-imports each module and every decorator fires again, so anything left
    behind would be a duplicate.

    NOTE: takes the paths, NOT the config. Discovery needs exactly this one
    list, and asking for the whole config meant startup had to build a config
    before the plugin schema existed, hand it over, then throw it away and build
    a second one — leaving a discarded object that looked usable. Narrowing the
    signature is what lets `SolveigConfig` be built once, fully composed.
    """
    # TODO: get rid of this. The SSOT is the config, everything derives from altering it.
    #  Plugin tools no longer have `clear` method, subcommands don't use theirs at all,
    #  hooks will follow to also not have it.
    clear_hooks()
    # A refused declaration warns from inside the import - caught here rather
    # than by a caller, so every scan records it whether or not anyone is
    # listening yet.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _succeeded, _failed, errors, on_disk_modules = rescan_and_load_plugins(plugins_config)

    scan = ScanResult(errors=errors, collisions=[str(w.message) for w in caught])

    # An entry whose file is gone keeps its value and loses its type.
    # `tool_class` is the class the plugin file defined, so its `__module__`
    # is that file, and the scan just listed which files still exist.
    # A None list means the scan never ran (the package is not importable) - that
    #  is not an empty one, and only an empty one means every plugin is gone.
    # NOTE: wrap the dict iteration in a list since we call `remove_type`
    #  which alters the thing being iterated
    if on_disk_modules is not None:
        for name, entry in list((plugins_config.tools.model_extra or {}).items()):
            if entry.tool_class.__module__ not in on_disk_modules:
                plugins_config.tools.remove_type(name)

    # Whatever derives from the plugin set updates itself now, before anything
    # can read a stale derivation. The config schema is the one that matters:
    # a config built against an un-recomposed schema silently hands back a raw
    # dict for a plugin's section instead of its typed model.
    for subscriber in ON_SCANNED:
        subscriber()
    return scan


async def report_plugins(
    plugins_config: PluginsConfig, interface: SolveigInterface, scan: ScanResult
) -> None:
    """Render discovered plugins in the Plugins dialog: every discovered tool is
    listed, a config-disabled one marked rather than hidden (list-all-mark-disabled),
    so a disabled plugin is visible instead of looking un-discovered. Any discovery
    errors surface first.

    `scan` is passed in rather than read off a module global: it is the result of
    the scan that filled the sections this renders, and the caller that ran it is
    the caller that has it."""
    async with interface.with_group("Plugins") as group:
        for error in scan.errors:
            await group.print(error, level=Level.ERROR)
        # A refused trigger is not a failed load, so it is a warning, not an error.
        for collision in scan.collisions:
            await group.print(collision, level=Level.WARNING)

        async with group.with_group("Tools") as tools_group:
            for tool_name, tool_config in sorted(plugins_config.tools):
                if tool_config.enabled:
                    await tools_group.print(f"'{tool_name}': loaded", level=Level.SUCCESS)
                else:
                    await tools_group.print(
                        f"'{tool_name}': loaded (disabled)", level=Level.INFO
                    )
            # PRESERVE + WARN: config for a plugin that wasn't discovered is kept
            # (see DynamicSection.unresolved) so /config save never strips it, but is
            # flagged here — a typo or a plugin missing on this machine, not an error.
            for unresolved_tool_name in sorted(plugins_config.tools.unresolved):
                await tools_group.print(
                    f"'{unresolved_tool_name}': config present but plugin not discovered (preserved)",
                    level=Level.WARNING,
                )

        async with group.with_group("Hooks") as hooks_group:
            for hook_name, hook_config in sorted(plugins_config.hooks):
                if hook_config.enabled:
                    await hooks_group.print(f"'{hook_name}': loaded", level=Level.SUCCESS)
                else:
                    await hooks_group.print(
                        f"'{hook_name}': loaded (disabled)", level=Level.INFO
                    )
            # Same PRESERVE + WARN as tools: a hook config block for an undiscovered
            # hook is kept (DynamicSection.unresolved) and flagged, never silently dropped.
            for unresolved_hook_name in sorted(plugins_config.hooks.unresolved):
                await hooks_group.print(
                    f"'{unresolved_hook_name}': config present but hook not discovered (preserved)",
                    level=Level.WARNING,
                )


__all__ = ["discover_plugins", "report_plugins", "PLUGIN_TARGETS"]
