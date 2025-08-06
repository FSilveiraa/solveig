import importlib
import pkgutil
from collections.abc import Callable


class HOOKS:
    before: list[tuple[Callable, tuple[type] | None]] = []
    after: list[tuple[Callable, tuple[type] | None]] = []

    # __init__ is called after instantiation, __new__ is called before
    def __new__(cls, *args, **kwargs):
        raise TypeError("HOOKS is a static registry and cannot be instantiated")


def _announce_register(verb, fun: Callable, requirements):
    req_types = (
        ", ".join([req.__name__ for req in requirements])
        if requirements
        else "any requirements"
    )
    print(f"🔌 Registering plugin `{fun.__name__}` to run {verb} {req_types}")


def before(requirements: tuple[type] | None = None):
    def register(fun: Callable):
        _announce_register("before", fun, requirements)
        HOOKS.before.append((fun, requirements))
        return fun

    return register


def after(requirements: tuple[type] | None = None):
    def register(fun):
        _announce_register("after", fun, requirements)
        HOOKS.after.append((fun, requirements))
        return fun

    return register


# Auto-discovery of hook plugins - any .py file in this directory
# that uses @before/@after decorators will be automatically registered
def load_hooks():
    """
    Discover and load all plugin files in the hooks directory.
    Any Python file that uses @before/@after decorators will auto-register.
    """
    print("🔍 Loading plugin hooks...")
    loaded_count = 0

    # Iterate through modules in this package
    for _, module_name, is_pkg in pkgutil.iter_modules(__path__, __name__ + "."):
        if not is_pkg and not module_name.endswith(".__init__"):
            try:
                importlib.import_module(module_name)
                loaded_count += 1
                plugin_name = module_name.split(".")[-1]
                print(f"   ✓ Loaded plugin file: {plugin_name}")
            except Exception as e:
                plugin_name = module_name.split(".")[-1]
                print(f"   ✗ Failed to load plugin {plugin_name}: {e}")

    total_hooks = len(HOOKS.before) + len(HOOKS.after)
    print(
        f"🎯 Plugin loading complete: {loaded_count} files, {total_hooks} hooks registered"
    )


# Expose only what plugin developers and the main system need
__all__ = ["HOOKS", "before", "after", "load_hooks"]
