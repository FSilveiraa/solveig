from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.plugins.utils import rescan_and_load_plugins
from solveig.schema.hooks import clear_hooks, registered_plugin_names


async def load_and_filter_hooks(config: SolveigConfig, interface: SolveigInterface):
    """Discover hook plugin modules and report which are active per `config.plugins`.

    Hooks register themselves into `solveig.schema.hooks` at import time via
    `@before`/`@after`; `HookRunner` gates each hook on `config.plugins` at
    call time, so there's nothing to enable/disable here beyond discovery and
    user-facing status.
    """
    clear_hooks()

    await rescan_and_load_plugins(
        plugin_module_path="solveig.plugins.hooks",
        interface=interface,
    )

    for plugin_name in sorted(registered_plugin_names()):
        if plugin_name in config.plugins:
            await interface.display_success(f"'{plugin_name}': Loaded")
        else:
            await interface.display_warning(
                f"'{plugin_name}': Skipped (missing from config)"
            )


__all__ = [
    "clear_hooks",
    "load_and_filter_hooks",
]
