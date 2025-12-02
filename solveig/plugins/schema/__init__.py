"""
Registry for dynamically discovered plugin requirements.
"""

from typing import TYPE_CHECKING, TypeVar

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.plugins.utils import rescan_and_load_plugins

# The `if TYPE_CHECKING:` block is a standard Python trick to solve a circular import problem.
#
# The Problem:
# 1. This file needs to know what a `Requirement` is for type hinting (`def register(cls: type[Requirement])`).
# 2. However, the file that defines `Requirement` (`solveig/schema/requirement/base.py`) needs
#    to import from the `plugins` package to run hooks.
# 3. This creates a circular dependency: `plugins` -> `schema` -> `plugins`, which would crash the application.
#
# The Solution:
# - At RUNTIME, `TYPE_CHECKING` is `False`. Python skips this import, breaking the circle. The code
#   still works due to Python's dynamic nature ("duck typing").
# - During STATIC ANALYSIS (when you run `mypy`), `TYPE_CHECKING` is `True`. The import happens,
#   allowing `mypy` to correctly validate the types.
if TYPE_CHECKING:
    from solveig.schema.requirement.base import Requirement

# A TypeVar is used to tell the type checker that the decorator returns the exact same class
# that it received as an argument. This preserves the specific type (e.g., `TreeRequirement`)
# for better static analysis downstream.
T = TypeVar("T", bound="Requirement")


class PLUGIN_REQUIREMENTS:
    all: dict[str, type["Requirement"]] = {}
    active: dict[str, type["Requirement"]] = {}

    def __new__(cls, *args, **kwargs):
        raise TypeError(
            "PLUGIN_REQUIREMENTS is a static registry and cannot be instantiated"
        )

    @classmethod
    def register(cls, requirement_class: T) -> T:
        """
        Registers a plugin requirement. Used as a decorator.
        Adds the requirement to the all_plugins master list.
        """
        cls.all[requirement_class.__name__] = requirement_class
        return requirement_class

    @classmethod
    def clear(cls):
        """Clear all registered plugin requirements (used by tests)."""
        cls.active.clear()
        cls.all.clear()  # TODO: may be necessary for true plugin reloading, but then we have to ensure that the reloading really... reloads classes from memory. AFAIK decorators don't get re-called from re-importing the module


async def load_and_filter_requirements(
    config: SolveigConfig, interface: SolveigInterface
):
    """
    Discover, load, and filter requirement plugins, and update the UI.
    Returns statistics dictionary.
    """
    PLUGIN_REQUIREMENTS.clear()

    await rescan_and_load_plugins(
        plugin_module_path="solveig.plugins.schema",
        interface=interface,
    )

    for plugin_name, requirement_class in PLUGIN_REQUIREMENTS.all.items():
        if config.plugins and plugin_name in config.plugins:
            PLUGIN_REQUIREMENTS.active[plugin_name] = requirement_class
            await interface.display_success(f"'{plugin_name}': Loaded")
        else:
            await interface.display_warning(
                f"'{plugin_name}': Skipped (missing from config)"
            )


register_requirement = PLUGIN_REQUIREMENTS.register

__all__ = [
    "PLUGIN_REQUIREMENTS",
    "register_requirement",
    "load_and_filter_requirements",
]
