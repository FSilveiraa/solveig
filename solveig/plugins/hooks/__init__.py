import importlib
import pkgutil
from collections.abc import Callable

from solveig import SolveigConfig
from solveig.interface import CLIInterface, SolveigInterface


class HOOKS:
    before: list[tuple[Callable, tuple[type] | None]] = []
    after: list[tuple[Callable, tuple[type] | None]] = []
    _all_hooks: dict[
        str,
        tuple[
            list[tuple[Callable, tuple[type] | None]],
            list[tuple[Callable, tuple[type] | None]],
        ],
    ] = {}

    # __init__ is called after instantiation, __new__ is called before
    def __new__(cls, *args, **kwargs):
        raise TypeError("HOOKS is a static registry and cannot be instantiated")


# def announce_register(plugin_name: str, before: list[tuple[Callable, list[type]]], after: list[tuple[Callable, list[type]]]):
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
    return "unknown"


def before(requirements: tuple[type] | None = None):
    def register(fun: Callable):
        plugin_name = _get_plugin_name_from_function(fun)
        # _announce_register("before", fun, requirements, plugin_name)

        # Store in both active hooks and all hooks registry
        hook_entry = (fun, requirements)
        HOOKS.before.append(hook_entry)

        # Store by plugin name for filtering
        if plugin_name not in HOOKS._all_hooks:
            HOOKS._all_hooks[plugin_name] = ([], [])
        HOOKS._all_hooks[plugin_name][0].append(hook_entry)

        return fun

    return register


def after(requirements: tuple[type] | None = None):
    def register(fun):
        plugin_name = _get_plugin_name_from_function(fun)
        # _announce_register("after", fun, requirements, plugin_name)

        # Store in both active hooks and all hooks registry
        hook_entry = (fun, requirements)
        HOOKS.after.append(hook_entry)

        # Store by plugin name for filtering
        if plugin_name not in HOOKS._all_hooks:
            HOOKS._all_hooks[plugin_name] = ([], [])
        HOOKS._all_hooks[plugin_name][1].append(hook_entry)

        return fun

    return register


# Auto-discovery of hook plugins - any .py file in this directory
# that uses @before/@after decorators will be automatically registered
def load_hooks(interface: SolveigInterface | None = None):
    """
    Discover and load plugin files in the hooks directory.
    """
    interface = interface or CLIInterface()
    # print("⌖ Loading plugin hooks...")

    import sys

    # Iterate through modules in this package
    total_files = 0
    with interface.with_group("Hook Plugins"):
        for _, module_name, is_pkg in pkgutil.iter_modules(__path__, __name__ + "."):
            if not is_pkg and not module_name.endswith(".__init__"):
                total_files += 1
                plugin_name = module_name.split(".")[-1]
                current_count = len(HOOKS._all_hooks)
                try:
                    # If module is already loaded and hooks were cleared, reload it
                    if module_name in sys.modules:
                        importlib.reload(sys.modules[module_name])
                    else:
                        importlib.import_module(module_name)
                    # check if we actually loaded something
                    if len(HOOKS._all_hooks) <= current_count:
                        interface.display_warning(
                            "Plugin `{}` was loaded, but did not register"
                        )

                    registered = HOOKS._all_hooks[plugin_name]
                    if registered:
                        # announce_register(plugin_name, before_hooks, after_hooks)
                        for fun, requirements in registered[0]:
                            announce_register(
                                "before", fun, requirements, plugin_name, interface
                            )
                        for fun, requirements in registered[1]:
                            announce_register(
                                "after", fun, requirements, plugin_name, interface
                            )

                        # interface.show(f"✓ Loaded plugin file: {plugin_name}")
                    # Not an error: we could have a schema-only plugin
                    # else:
                    #     print(f"   ✗ Plugin loaded, but failed to register: {plugin_name}: {e}")
                except Exception as e:
                    interface.display_error(f"Failed to load plugin {plugin_name}: {e}")

        interface.show(
            f"🕮  Hook plugin loading complete: {total_files} files, {len(HOOKS._all_hooks)} hooks"
        )


def filter_hooks(
    interface: SolveigInterface, enabled_plugins: set[str] | SolveigConfig | None
):
    """
    Filters currently loaded plugins according to config

    Args:
    enabled_plugins: If provided, only activate plugins whose names are in this set.
                    If None, loads all discovered plugins (used during schema init).
    :return:
    """
    if HOOKS._all_hooks:
        enabled_plugins = enabled_plugins or set()
        if isinstance(enabled_plugins, SolveigConfig):
            enabled_plugins = set(enabled_plugins.plugins.keys())
        with interface.with_group("Filtering hook plugins", count=len(enabled_plugins)):
            # Clear current hooks and rebuild from registry
            HOOKS.before.clear()
            HOOKS.after.clear()

            interface.current_level += 1
            for plugin_name in HOOKS._all_hooks:
                if plugin_name in enabled_plugins:
                    before_hooks, after_hooks = HOOKS._all_hooks[plugin_name]
                    HOOKS.before.extend(before_hooks)
                    HOOKS.after.extend(after_hooks)
                else:
                    interface.show(
                        f"≫ Skipping hook plugin, not present in config: {plugin_name}"
                    )
            interface.current_level -= 1

            total_hooks = len(HOOKS.before) + len(HOOKS.after)
            interface.show(
                f"🕮  Hook filtering complete: {len(enabled_plugins)} plugins, {total_hooks} hooks active"
            )
            return


# Expose only what plugin developers and the main system need
__all__ = ["HOOKS", "before", "after", "filter_hooks"]
