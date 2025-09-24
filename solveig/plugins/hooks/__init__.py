import importlib
import pkgutil
import sys
from collections.abc import Callable

from solveig import SolveigConfig
from solveig.interface import SolveigInterface


class HOOKS:
    before: list[tuple[Callable, tuple[type, ...] | None]] = []
    after: list[tuple[Callable, tuple[type, ...] | None]] = []
    all_hooks: dict[
        str,
        tuple[
            dict[str, tuple[Callable, tuple[type, ...] | None]],
            dict[str, tuple[Callable, tuple[type, ...] | None]],
        ],
    ] = {}

    # __init__ is called after instantiation, __new__ is called before
    def __new__(cls, *args, **kwargs):
        raise TypeError("HOOKS is a static registry and cannot be instantiated")


def announce_register(
    verb, fun: Callable, requirements, plugin_name: str, interface: SolveigInterface
):
    req_types = (
        ", ".join([req.__name__ for req in requirements])
        if requirements
        else "any requirements"
    )
    interface.display_text(
        f"ϟ Registering plugin `{plugin_name}.{fun.__name__}` to run {verb} {req_types}"
    )


def _get_plugin_name_from_function(fun: Callable) -> str:
    """Extract plugin name from function module path."""
    module = fun.__module__
    if ".hooks." in module:
        # Extract plugin name from module path like 'solveig.plugins.hooks.shellcheck'
        return module.split(".hooks.")[-1]
    return fun.__name__


def before(requirements: tuple[type, ...] | None = None):
    def register(fun: Callable):
        plugin_name = _get_plugin_name_from_function(fun)
        if plugin_name not in HOOKS.all_hooks:
            HOOKS.all_hooks[plugin_name] = ({}, {})
        # Use function name as key to prevent duplicates
        HOOKS.all_hooks[plugin_name][0][fun.__name__] = (fun, requirements)
        return fun

    return register


def after(requirements: tuple[type, ...] | None = None):
    def register(fun):
        plugin_name = _get_plugin_name_from_function(fun)
        if plugin_name not in HOOKS.all_hooks:
            HOOKS.all_hooks[plugin_name] = ({}, {})
        # Use function name as key to prevent duplicates
        HOOKS.all_hooks[plugin_name][1][fun.__name__] = (fun, requirements)
        return fun

    return register


def load_and_filter_hooks(
    interface: SolveigInterface,
    enabled_plugins: set[str] | SolveigConfig | None,
    allow_all: bool = False,
) -> dict[str, int]:
    """
    Discover, load, and filter hook plugins in one step.
    Returns statistics dictionary.
    """
    # HOOKS.all_hooks.clear()
    HOOKS.before.clear()
    HOOKS.after.clear()

    # Convert config to plugin set
    if isinstance(enabled_plugins, SolveigConfig):
        enabled_plugins = set(enabled_plugins.plugins.keys())

    loaded_plugins = []
    active_hooks = 0

    # First: Load filesystem-based hook plugins (this registers them via decorators)
    for _, module_name, is_pkg in pkgutil.iter_modules(__path__, __name__ + "."):
        if not is_pkg and not module_name.endswith(".__init__"):
            plugin_name = module_name.split(".")[-1]

            try:
                # Import/reload module (this registers hooks in HOOKS.all_hooks via decorators)
                if module_name in sys.modules:
                    importlib.reload(sys.modules[module_name])
                else:
                    importlib.import_module(module_name)

            except Exception as e:
                interface.display_error(f"Hook plugin {plugin_name}: {e}")

    # Second: Process ALL plugins in HOOKS.all_hooks (filesystem + memory-registered)
    for plugin_name, (before_dict, after_dict) in HOOKS.all_hooks.items():
        loaded_plugins.append(plugin_name)

        if allow_all or (enabled_plugins and plugin_name in enabled_plugins):
            # Add to active hooks (convert dict values back to list)
            HOOKS.before.extend(before_dict.values())
            HOOKS.after.extend(after_dict.values())
            active_hooks += len(before_dict) + len(after_dict)
            interface.display_text(f"'{plugin_name}': Loaded")
        else:
            interface.display_warning(f"'{plugin_name}': Skipped (missing from config)")

    interface.display_text(
        f"Hooks: {len(loaded_plugins)} plugins loaded, {active_hooks} active"
    )

    return {"loaded": len(loaded_plugins), "active": active_hooks}


def clear_hooks():
    HOOKS.before.clear()
    HOOKS.after.clear()
    HOOKS.all_hooks.clear()


# Expose only what plugin developers and the main system need
__all__ = ["HOOKS", "before", "after", "load_and_filter_hooks"]
