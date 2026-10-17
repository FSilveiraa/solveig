"""Finding plugins, typing what they declare, and saying what was found.

`discover_plugins(plugins_config, interface)` is the ONE path a change to the
plugin set travels — startup, a `plugins.paths` change, and (later)
`/plugins reload` all take it. It is `async`, and it owns the whole job: it
imports whatever is on disk, types the plugin sections of that config, gathers
the async observers its writes reached, and reports the outcome. The import
itself writes nothing — the decorators record their declarations (name, config
model, module) under `solveig.plugins.scan.SCAN_DECLARATIONS`, and after the
imports this module types the sections, one batched `set_type` per plugin
module, so a failure is attributable to the plugin that caused it and a plugin
is notified as a whole. It also removes the type of an entry whose file is
gone.

The entrypoint being `async` is what makes the observer contract structural:
discovery writes to the config, and a write that reaches an async observer
needs a context that can await — there is no sync caller to get this wrong,
and a forgotten `await` is Python's own `RuntimeWarning`.

NOTE: this is a real module rather than the package `__init__`, which is empty.
An `__init__` runs whenever anything under it is imported, so re-exporting here
would put `plugins.tools` in front of `plugins.hooks` for every importer —
including `orchestration`, which `plugins.tools` imports back for `@tool`.
"""

import asyncio
import importlib
import os
import pkgutil
import sys
import warnings
from collections.abc import Awaitable

from solveig.interface.base import Level, SolveigInterface
from solveig.plugins.scan import SCAN_DECLARATIONS

from .config import PluginsConfig
from .hooks import HookConfig

#: The one package the scan walks. External dirs are folded into its `__path__`,
#: so a bundled and an external plugin are indistinguishable from here on.
PLUGIN_PACKAGE = "solveig.plugins.library"


def _rescan_and_load_plugins(
    plugins_config: PluginsConfig, plugin_module_path: str = "solveig.plugins.library"
) -> tuple[int, int, list[str], set[str] | None, dict]:
    """Import every module on disk under `plugin_module_path`, collecting what
    their decorators declare.

    Writes no config: the declarations come back as a `dict[name ->
    PluginDeclaration]` for the caller (`discover_plugins`) to type the
    sections with, grouped however it likes. The scan's context is set around
    the import loop only — a decorator outside it is an error, because there
    would be no scan to type the entry with."""
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
        return (
            0,
            0,
            [f"Plugin discovery path not found: {plugin_module_path}"],
            None,
            {},
        )

    # 3. Find all relevant modules already in memory.
    in_memory_modules = {
        name for name in sys.modules if name.startswith(f"{plugin_module_path}.")
    }

    # 4. Remove any modules from memory that are no longer on disk.
    modules_to_unload = in_memory_modules - on_disk_modules
    for module_name in modules_to_unload:
        del sys.modules[module_name]

    # 5. Iterate through what's on disk and sync memory. What these imports
    #  declare lands on the scan's context, for as long as they run.
    declarations: dict = {}
    token = SCAN_DECLARATIONS.set(declarations)
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
                errors.append(
                    f"Failed to load or reload plugin module {module_name}: {e}"
                )
                failed += 1
    finally:
        SCAN_DECLARATIONS.reset(token)

    return succeeded, failed, errors, on_disk_modules, declarations


async def discover_plugins(
    plugins_config: PluginsConfig, interface: SolveigInterface
) -> None:
    """The ONE path a change to the plugin set travels — startup, a
    `plugins.paths` change, and (later) `/plugins reload` all take it.

    Discovery alone was never the whole job: whoever ran it also had to await
    the async observers its writes reached and render the report, and each call
    site had to remember a different subset. That is the fetch → check → act
    shape this project is written against, so the obligations live here — the
    same argument that makes `Conversation.load()` fire the events a live turn
    fires. Folding them in is also what makes the async-observer contract
    structural: an entrypoint that must be awaited cannot be called from a
    context that cannot await, so there is no sync caller for a config write to
    strand coroutines with.

    ONE scan, not one per surface. A plugin declares tools, hooks and
    subcommands with decorators, and a decorator does not care where the file
    sits — so scanning per surface only meant a plugin wanting two of them had
    to be two files, imported by two passes and cleared by two calls.

    NOTE: takes the plugin section, NOT the whole config. Discovery needs
    exactly the plugin settings, and asking for the whole config meant startup
    had to build a config before the plugin schema existed, hand it over, then
    throw it away and build a second one — leaving a discarded object that
    looked usable. Narrowing the signature is what lets `SolveigConfig` be
    built once."""
    # A refused declaration warns from inside the import - caught here rather
    # than by a caller, so every scan records it whether or not anyone is
    # listening yet.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _succeeded, _failed, errors, on_disk_modules, declarations = (
            _rescan_and_load_plugins(plugins_config)
        )

    collisions = [str(w.message) for w in caught or []]

    # Type the declared entries: one batched `set_type` per plugin module, so a
    # plugin is notified as a whole and a failure names the module it came
    # from (the declaration carried it; the write no longer runs inside the
    # import, where that attribution was free). Earlier entries of a failing
    # module stay applied, like a `set` whose later path fails.
    #
    # The config model's own base says which section an entry belongs to — a
    # `HookConfig` subclass is a hook, anything else is a tool — so the scan
    # routes without the decorator having to name a section.
    tools_by_module: dict[str, dict[str, type]] = {}
    hooks_by_module: dict[str, dict[str, type]] = {}
    for declaration in declarations.values():
        by_module = (
            hooks_by_module
            if issubclass(declaration.config_model, HookConfig)
            else tools_by_module
        )
        by_module.setdefault(declaration.module, {})[declaration.name] = (
            declaration.config_model
        )
    pending: list[Awaitable] = []
    for section, by_module in (
        (plugins_config.tools, tools_by_module),
        (plugins_config.hooks, hooks_by_module),
    ):
        for module, types in by_module.items():
            try:
                pending.extend(section.set_type(**types))
            except Exception as error:
                errors.append(
                    f"Plugin module {module} failed to type its entries: {error}"
                )

    # An entry whose file is gone keeps its value and loses its type.
    # `tool_class` is the class the plugin file defined, so its `__module__`
    # is that file, and the scan just listed which files still exist. An entry
    # with no `tool_class` is an unowned block — config for a tool that was
    # never discovered — and belongs to nothing on disk: kept until its tool
    # appears. A None module set means the scan never ran (the package is not
    # importable) - that is not an empty one, and only an empty one means every
    # plugin is gone.
    if on_disk_modules is not None:
        # NOTE: wrap the section iteration in a list, since `remove_type`
        #  alters the thing being iterated
        tool_gone = [
            name
            for name, entry in list((plugins_config.tools.model_extra or {}).items())
            if entry.tool_class and entry.tool_class.__module__ not in on_disk_modules
        ]
        # A hook wrapper stores the plugin file it came from as `module`
        #  (its class lives in `plugins.hooks`, so `__module__` would lie).
        hook_gone = [
            name
            for name, entry in list((plugins_config.hooks.model_extra or {}).items())
            if entry.hook and entry.hook.module not in on_disk_modules
        ]
        if tool_gone:
            pending.extend(plugins_config.tools.remove_type(*tool_gone))
        if hook_gone:
            pending.extend(plugins_config.hooks.remove_type(*hook_gone))

    # Whatever the writes reached runs before anything can read a half-updated
    #  derivation; the report follows, so what it renders is post-observer.
    if pending:
        await asyncio.gather(*pending)
    await _report_plugins(plugins_config, interface, errors, collisions)


async def _report_plugins(
    plugins_config: PluginsConfig,
    interface: SolveigInterface,
    errors: list[str],
    collisions: list[str],
) -> None:
    """Render discovered plugins in the Plugins dialog: every discovered tool is
    listed, a config-disabled one marked rather than hidden (list-all-mark-disabled),
    so a disabled plugin is visible instead of looking un-discovered. Any discovery
    errors surface first.

    Private to this module: `discover_plugins` is the one caller, and the lists
    it passes are the ones this same call produced — nothing travels farther
    than the function boundary that created them."""
    async with interface.with_group("Plugins") as group:
        for error in errors:
            await group.print(error, level=Level.ERROR)
        # A refused trigger is not a failed load, so it is a warning, not an error.
        for collision in collisions:
            await group.print(collision, level=Level.WARNING)

        async with group.with_group("Tools") as tools_group:
            for tool_name, tool_config in sorted(plugins_config.tools):
                if tool_config.enabled:
                    await tools_group.print(
                        f"'{tool_name}': loaded", level=Level.SUCCESS
                    )
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
                    await hooks_group.print(
                        f"'{hook_name}': loaded", level=Level.SUCCESS
                    )
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


__all__ = ["discover_plugins"]
