"""Plugin system for Solveig.

Discovery is split from reporting: `discover_plugins(config)` populates the tool
and hook registries (idempotent, UI-free, callable on demand — so it can run
before the interface exists, which the two-phase config bootstrap needs to
compose `plugins.tools` before the config is threaded anywhere). `report_plugins`
renders the outcome in the Plugins dialog afterwards.
"""

from solveig.config import SolveigConfig
from solveig.interface.base import SolveigInterface

from .hooks import (
    after,
    before,
    clear_hooks,
    hooks_config_map,
    load_and_filter_plugin_hooks,
)
from .tools import (
    PLUGIN_TOOLS,
    clear_tools,
    load_and_filter_plugin_tools,
    plugin_tool_name,
    tool,
)
from .utils import register_external_plugin_paths


def discover_plugins(paths: list[str]) -> list[str]:
    """Discover all plugin tools + hooks into their registries — idempotent and
    UI-free. Folds the external dirs in `paths` into the built-in packages
    first, then scans. Returns discovery error messages; the caller surfaces
    them (via `report_plugins`). Kept reporting-free so discovery can run
    before the interface exists.

    NOTE: takes the paths, NOT the config. Discovery needs exactly this one
    list, and asking for the whole config meant startup had to build a config
    before the plugin schema existed, hand it over, then throw it away and build
    a second one — leaving a discarded object that looked usable. Narrowing the
    signature is what lets `SolveigConfig` be built once, fully composed.
    """
    register_external_plugin_paths(paths)
    errors = load_and_filter_plugin_tools()
    errors += load_and_filter_plugin_hooks()
    return errors


async def report_plugins(
    config: SolveigConfig, interface: SolveigInterface, errors: list[str]
) -> None:
    """Render discovered plugins in the Plugins dialog: every discovered tool is
    listed, a config-disabled one marked rather than hidden (list-all-mark-disabled),
    so a disabled plugin is visible instead of looking un-discovered. Any discovery
    errors surface first."""
    async with interface.with_group("Plugins") as group:
        for error in errors:
            await group.display_error(error)

        async with group.with_group("Tools") as tools_group:
            for name in sorted(plugin_tool_name(entry) for entry in PLUGIN_TOOLS):
                if config.is_tool_enabled(name):
                    await tools_group.display_success(f"'{name}': loaded")
                else:
                    await tools_group.display_info(f"'{name}': loaded (disabled)")
            # PRESERVE + WARN: config for a plugin that wasn't discovered is kept
            # (see PreservingSection.undiscovered) so /config save never strips it, but is
            # flagged here — a typo or a plugin missing on this machine, not an error.
            for name in sorted(config.plugins.tools.undiscovered):
                await tools_group.display_warning(
                    f"'{name}': config present but plugin not discovered (preserved)"
                )

        async with group.with_group("Hooks") as hooks_group:
            for name in sorted(hooks_config_map()):
                if config.is_hook_enabled(name):
                    await hooks_group.display_success(f"'{name}': loaded")
                else:
                    await hooks_group.display_info(f"'{name}': loaded (disabled)")
            # Same PRESERVE + WARN as tools: a hook config block for an undiscovered
            # hook is kept (PreservingSection) and flagged, never silently dropped.
            for name in sorted(config.plugins.hooks.undiscovered):
                await hooks_group.display_warning(
                    f"'{name}': config present but hook not discovered (preserved)"
                )


def clear_plugins() -> None:
    clear_hooks()
    clear_tools()


__all__ = [
    "discover_plugins",
    "report_plugins",
    "clear_plugins",
    "tool",
    "before",
    "after",
]
