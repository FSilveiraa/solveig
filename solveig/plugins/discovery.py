"""Finding plugins, and saying what was found.

Discovery is split from reporting: `discover_plugins(paths)` populates the tool,
hook and subcommand registries (idempotent, UI-free, callable on demand — so it
can run before the interface exists, which the config bootstrap needs in order to
compose `plugins.tools` before the config is threaded anywhere). `report_plugins`
renders the outcome in the Plugins dialog afterwards.

NOTE: this is a real module rather than the package `__init__`, which is empty.
An `__init__` runs whenever anything under it is imported, so re-exporting here
would put `plugins.tools` in front of `plugins.hooks` for every importer —
including `orchestration`, which `plugins.tools` imports back for `@tool`.
"""

import warnings
from collections.abc import Callable
from dataclasses import dataclass, field

from solveig.config import SolveigConfig
from solveig.interface.base import Level, SolveigInterface

from .hooks import clear_hooks, hooks_config_map
from .subcommands import clear_subcommands
from .tools import PLUGIN_TOOLS, clear_tools, plugin_tool_name
from .utils import register_external_plugin_paths, rescan_and_load_plugins

#: The one package the scan walks. External dirs are folded into its `__path__`,
#: so a bundled and an external plugin are indistinguishable from here on.
PLUGIN_PACKAGE = "solveig.plugins.library"


@dataclass
class ScanResult:
    """What the last scan produced, kept so it can be REPORTED later.

    Discovery runs before the interface exists (the config bootstrap needs the
    schema composed before anything is threaded anywhere), so whatever it has to
    say has nowhere to go at the time. Handing the errors back to the caller
    made every caller responsible for carrying them to a display, and the only
    way to report at startup was to run the whole scan a second time once the
    interface was up.

    `errors` are modules that failed to import. `collisions` are refused
    declarations - a plugin claiming a trigger another store already holds -
    which arrive as warnings from inside the import, the only channel available
    there. They are kept apart: a refused trigger is not a failure to load, and
    rendering it as one misreports a working plugin.
    """

    errors: list[str] = field(default_factory=list)
    collisions: list[str] = field(default_factory=list)


LAST_SCAN = ScanResult()

#: Fired once per scan, after the registries are refilled. Plain callables, so
#: this module needs to know nothing about its subscribers - the doorbell
#: pattern `UserMessageQueue.on_change` already uses.
#:
#: Batched BY CONSTRUCTION: the notification lives on the scan, not on each
#: registration, because a scan is the only thing that changes the plugin set.
#: Firing per registration would make each subscriber's work quadratic - one
#: full `model_rebuild` per hook over a growing field set, measured at 3.4s for
#: 200 hooks - and the registry could not stop a subscriber holding it wrong.
ON_SCANNED: list[Callable[[], None]] = []


def discover_plugins(paths: list[str]) -> list[str]:
    """Load every plugin into the registries it declares into — idempotent and
    UI-free. Folds the external dirs in `paths` into the library package first,
    then scans it once. Returns discovery error messages; the caller surfaces
    them (via `report_plugins`). Kept reporting-free so discovery can run
    before the interface exists.

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
    register_external_plugin_paths(paths)
    clear_plugins()
    # A refused declaration warns from inside the import - caught here rather
    # than by a caller, so every scan records it whether or not anyone is
    # listening yet.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _succeeded, _failed, errors = rescan_and_load_plugins(PLUGIN_PACKAGE)

    LAST_SCAN.errors = errors
    LAST_SCAN.collisions = [str(w.message) for w in caught]
    # Whatever derives from the plugin set updates itself now, before anything
    # can read a stale derivation. The config schema is the one that matters:
    # a config built against an un-recomposed schema silently hands back a raw
    # dict for a plugin's section instead of its typed model.
    for subscriber in ON_SCANNED:
        subscriber()
    return errors


async def report_plugins(config: SolveigConfig, interface: SolveigInterface) -> None:
    """Render discovered plugins in the Plugins dialog: every discovered tool is
    listed, a config-disabled one marked rather than hidden (list-all-mark-disabled),
    so a disabled plugin is visible instead of looking un-discovered. Any discovery
    errors surface first.

    Reads the registries and `LAST_SCAN` live rather than taking them as
    arguments, so reporting can happen whenever an interface exists - which is
    what lets startup scan ONCE and report later, instead of scanning a second
    time just to have the errors in hand."""
    async with interface.with_group("Plugins") as group:
        for error in LAST_SCAN.errors:
            await group.print(error, level=Level.ERROR)
        # A refused trigger is not a failed load, so it is a warning, not an error.
        for collision in LAST_SCAN.collisions:
            await group.print(collision, level=Level.WARNING)

        async with group.with_group("Tools") as tools_group:
            for name in sorted(plugin_tool_name(entry) for entry in PLUGIN_TOOLS):
                if config.is_tool_enabled(name):
                    await tools_group.print(f"'{name}': loaded", level=Level.SUCCESS)
                else:
                    await tools_group.print(
                        f"'{name}': loaded (disabled)", level=Level.INFO
                    )
            # PRESERVE + WARN: config for a plugin that wasn't discovered is kept
            # (see PreservingSection.undiscovered) so /config save never strips it, but is
            # flagged here — a typo or a plugin missing on this machine, not an error.
            for name in sorted(config.plugins.tools.undiscovered):
                await tools_group.print(
                    f"'{name}': config present but plugin not discovered (preserved)",
                    level=Level.WARNING,
                )

        async with group.with_group("Hooks") as hooks_group:
            for name in sorted(hooks_config_map()):
                if config.is_hook_enabled(name):
                    await hooks_group.print(f"'{name}': loaded", level=Level.SUCCESS)
                else:
                    await hooks_group.print(
                        f"'{name}': loaded (disabled)", level=Level.INFO
                    )
            # Same PRESERVE + WARN as tools: a hook config block for an undiscovered
            # hook is kept (PreservingSection) and flagged, never silently dropped.
            for name in sorted(config.plugins.hooks.undiscovered):
                await hooks_group.print(
                    f"'{name}': config present but hook not discovered (preserved)",
                    level=Level.WARNING,
                )


def clear_plugins() -> None:
    """Empty every registry a plugin can declare into. Run before each scan (and
    in tests) — one call, because a plugin is one file that may have declared
    into all three."""
    clear_hooks()
    clear_tools()
    clear_subcommands()


__all__ = ["discover_plugins", "report_plugins", "clear_plugins"]
