import importlib
import pkgutil
import sys
from collections.abc import Callable

from solveig import SolveigConfig
from solveig.interface import SolveigInterface


class HOOKS:
    before: list[tuple[Callable, tuple[type] | None]] = []
    after: list[tuple[Callable, tuple[type] | None]] = []
    all_hooks: dict[
        str,
        tuple[
            list[tuple[Callable, tuple[type] | None]],
            list[tuple[Callable, tuple[type] | None]],
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
    interface.show(
        f"ϟ Registering plugin `{plugin_name}.{fun.__name__}` to run {verb} {req_types}"
    )


def _get_plugin_name_from_function(fun: Callable) -> str:
    """Extract plugin name from function module path."""
    module = fun.__module__
    if ".hooks." in module:
        # Extract plugin name from module path like 'solveig.plugins.hooks.shellcheck'
        return module.split(".hooks.")[-1]
    return fun.__name__


def before(requirements: tuple[type] | None = None):
    def register(fun: Callable):
        plugin_name = _get_plugin_name_from_function(fun)
        if plugin_name not in HOOKS.all_hooks:
            HOOKS.all_hooks[plugin_name] = ([], [])
        HOOKS.all_hooks[plugin_name][0].append((fun, requirements))
        return fun

    return register


def after(requirements: tuple[type] | None = None):
    def register(fun):
        plugin_name = _get_plugin_name_from_function(fun)
        if plugin_name not in HOOKS.all_hooks:
            HOOKS.all_hooks[plugin_name] = ([], [])
        HOOKS.all_hooks[plugin_name][1].append((fun, requirements))
        return fun

    return register


def load_and_filter_hooks(
    interface: SolveigInterface, enabled_plugins: set[str] | SolveigConfig | None
) -> dict[str, int]:
    """
    Discover, load, and filter hook plugins in one step.
    Returns statistics dictionary.
    """
    HOOKS.all_hooks.clear()
    HOOKS.before.clear()
    HOOKS.after.clear()
    
    # Convert config to plugin set
    if isinstance(enabled_plugins, SolveigConfig):
        enabled_plugins = set(enabled_plugins.plugins.keys())
    
    loaded_plugins = []
    active_hooks = 0
    
    # Load all hook plugins
    for _, module_name, is_pkg in pkgutil.iter_modules(__path__, __name__ + "."):
        if not is_pkg and not module_name.endswith(".__init__"):
            plugin_name = module_name.split(".")[-1]
            
            try:
                # Import/reload module
                if module_name in sys.modules:
                    importlib.reload(sys.modules[module_name])
                else:
                    importlib.import_module(module_name)
                
                # Check if plugin should be enabled
                if plugin_name in HOOKS.all_hooks:
                    loaded_plugins.append(plugin_name)
                    
                    if enabled_plugins is None or plugin_name in enabled_plugins:
                        # Add to active hooks
                        before_hooks, after_hooks = HOOKS.all_hooks[plugin_name]
                        HOOKS.before.extend(before_hooks)
                        HOOKS.after.extend(after_hooks)
                        active_hooks += len(before_hooks) + len(after_hooks)
                        interface.show(f"'{plugin_name}': Loaded")
                    else:
                        interface.display_warning(f"'{plugin_name}': Skipped (missing from config)")
                        
            except Exception as e:
                interface.display_error(f"Hook plugin {plugin_name}: {e}")
    
    interface.show(
        f"Hooks: {len(loaded_plugins)} plugins loaded, {active_hooks} active"
    )
    
    return {
        'loaded': len(loaded_plugins),
        'active': active_hooks
    }


# Legacy function - kept for compatibility
def load_requirement_hooks(interface: SolveigInterface):
    """Legacy function - use load_and_filter_hooks instead."""
    return load_and_filter_hooks(interface, None)

def filter_hooks(
    interface: SolveigInterface, enabled_plugins: set[str] | SolveigConfig | None
):
    """Legacy function - use load_and_filter_hooks instead."""
    return load_and_filter_hooks(interface, enabled_plugins)


def clear_hooks():
    HOOKS.before.clear()
    HOOKS.after.clear()
    HOOKS.all_hooks.clear()


# Expose only what plugin developers and the main system need
__all__ = ["HOOKS", "before", "after", "load_and_filter_hooks", "filter_hooks"]
