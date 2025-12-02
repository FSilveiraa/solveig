from collections import defaultdict
from collections.abc import Callable

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.plugins.utils import rescan_and_load_plugins

# Don't ask me to explain what meta-level of Python we're on at this point, but MyPy needs this
type HookEntry = list[tuple[Callable, tuple[type, ...] | None]]


class HOOKS:
    before: list[tuple[Callable, tuple[type, ...] | None]] = []
    after: list[tuple[Callable, tuple[type, ...] | None]] = []
    all: dict[
        str,
        tuple[
            HookEntry, HookEntry
            # list[tuple[Callable, tuple[type, ...] | None]],
        ],
    ] = defaultdict(lambda: ([], []))

    def __new__(cls, *args, **kwargs):
        raise TypeError("HOOKS is a static registry and cannot be instantiated")


def _get_plugin_name_from_function(fun: Callable) -> str:
    """Extract plugin name from function module path."""
    module = fun.__module__
    if ".hooks." in module:
        return module.split(".hooks.")[-1]
    return fun.__name__


def before(requirements: tuple[type, ...] | None = None):
    def register(fun: Callable):
        plugin_name = _get_plugin_name_from_function(fun)
        HOOKS.all[plugin_name][0].append((fun, requirements))
        return fun

    return register


def after(requirements: tuple[type, ...] | None = None):
    def register(fun):
        plugin_name = _get_plugin_name_from_function(fun)
        HOOKS.all[plugin_name][1].append((fun, requirements))
        return fun

    return register


async def load_and_filter_hooks(config: SolveigConfig, interface: SolveigInterface):
    """
    Discover, load, and filter hook plugins, and update the UI.
    """
    clear_hooks()

    await rescan_and_load_plugins(
        plugin_module_path="solveig.plugins.hooks",
        interface=interface,
    )

    for plugin_name, (before_hooks, after_hooks) in HOOKS.all.items():
        if config.plugins and plugin_name in config.plugins:
            HOOKS.before.extend(before_hooks)
            HOOKS.after.extend(after_hooks)
            await interface.display_success(f"'{plugin_name}': Loaded")
        else:
            await interface.display_warning(
                f"'{plugin_name}': Skipped (missing from config)"
            )


def clear_hooks():
    HOOKS.before.clear()
    HOOKS.after.clear()
    HOOKS.all.clear()


__all__ = ["HOOKS", "before", "after", "load_and_filter_hooks", "clear_hooks"]
