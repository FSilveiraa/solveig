import importlib
import pkgutil
from typing import Optional, Tuple, List, Callable, Type

class HOOKS:
    before: List[Tuple[Callable, Optional[Tuple[Type]]]] = []
    after: List[Tuple[Callable, Optional[Tuple[Type]]]] = []

    # __init__ is called after instantiation, __new__ is called before
    def __new__(cls, *args, **kwargs):
        raise TypeError("HOOKS is a static registry and cannot be instantiated")


def _announce_register(verb, fun, requirements):
    print(f"Registering plugin `{fun}` to run {verb} {f"requirements of types: [{requirements}]" if requirements else "any requirements"}")


def before(requirements:Optional[Tuple[type]] = None):
    def register(fun: Callable):
        _announce_register("before", fun, requirements)
        HOOKS.before.append((fun, requirements))
        return fun
    return register


def after(requirements:Optional[Tuple[type]] = None):
    def register(fun):
        _announce_register("after", fun, requirements)
        HOOKS.after.append((fun, requirements))
        return fun
    return register


# shamelessly copied off the internet, this is pretty low-level and obscure
# the idea is that we can drop a python file inside `/plugins/hooks/` decorated with @before/after(...) and
# it should auto-register, but that only happens if you explicitly import that file
# This HAS to be called at run-time in order for hooks to be found and used
def load_hooks():
    # iterate through modules in this package
    for _, module_name, is_pkg in pkgutil.iter_modules(__path__, __name__ + "."):
        if not is_pkg:
            importlib.import_module(module_name)
