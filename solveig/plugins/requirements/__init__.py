"""Requirement plugins - new operation types that extend Solveig's capabilities."""

import importlib
import pkgutil
from typing import TYPE_CHECKING

from solveig.interface import CLIInterface, SolveigInterface

if TYPE_CHECKING:
    from solveig import SolveigConfig
    from solveig.schema.requirements.base import Requirement
    from solveig.schema.results.base import RequirementResult


class REQUIREMENTS:
    """Registry for dynamically discovered requirement plugins."""

    registered: dict[str, type["Requirement"]] = {}
    _all_requirements: dict[str, type["Requirement"]] = {}
    _plugin_results: list[type["RequirementResult"]] = (
        []
    )  # Result types that need model_rebuild()

    def __new__(cls, *args, **kwargs):
        raise TypeError("REQUIREMENTS is a static registry and cannot be instantiated")


def register_requirement(requirement_class: type["Requirement"]):
    """
    Decorator to register a requirement plugin.

    Usage:
    @register_requirement
    class MyRequirement(Requirement):
        ...
    """
    # Store in both active and all requirements registry
    REQUIREMENTS.registered[requirement_class.__name__] = requirement_class
    REQUIREMENTS._all_requirements[requirement_class.__name__] = requirement_class

    return requirement_class


def register_plugin_result(result_class: type["RequirementResult"]):
    """Register a plugin result type that needs model_rebuild()."""
    REQUIREMENTS._plugin_results.append(result_class)


def _get_plugin_name_from_class(cls: type) -> str:
    """Extract plugin name from class module path."""
    module = cls.__module__
    if ".requirements." in module:
        # Extract plugin name from module path like 'solveig.plugins.requirements.tree'
        return module.split(".requirements.")[-1]
    return "unknown"


def load_requirements(interface: SolveigInterface | None = None):
    """
    Discover and load requirement plugin files in the requirements directory.
    Similar to hooks.load_hooks() but for requirement types.
    """
    interface = interface or CLIInterface()

    import sys

    total_files = 0
    total_requirements = 0

    with interface.with_group("Requirement Plugins"):
        for _, module_name, is_pkg in pkgutil.iter_modules(__path__, __name__ + "."):
            if not is_pkg and not module_name.endswith(".__init__"):
                total_files += 1
                plugin_name = module_name.split(".")[-1]
                # current_count = len(REQUIREMENTS._all_requirements)

                try:
                    # Get the keys that existed before loading this module
                    before_keys = list(REQUIREMENTS._all_requirements.keys())

                    # Import the module
                    if module_name in sys.modules:
                        importlib.reload(sys.modules[module_name])
                    else:
                        importlib.import_module(module_name)

                    # Find newly added requirements
                    new_requirement_names = [
                        name
                        for name in REQUIREMENTS._all_requirements.keys()
                        if name not in before_keys
                    ]

                    if new_requirement_names:
                        total_requirements += len(new_requirement_names)
                        for req_name in new_requirement_names:
                            interface.show(f"✓ Loaded {plugin_name}.{req_name}")
                    else:
                        interface.show(
                            f"≫ Plugin {plugin_name} loaded but registered no requirements"
                        )

                except Exception as e:
                    interface.display_error(
                        f"Failed to load requirement plugin {plugin_name}: {e}"
                    )

        interface.show(
            f"🕮  Requirement plugin loading complete: {total_files} files, {total_requirements} requirements"
        )

    # Rebuild all registered plugin result models
    for result_class in REQUIREMENTS._plugin_results:
        try:
            result_class.model_rebuild()
        except Exception:
            pass  # If rebuild fails, continue silently


def filter_requirements(
    interface: SolveigInterface, enabled_plugins: "set[str] | SolveigConfig | None"
):
    """
    Filters currently loaded requirements according to config

    Args:
    enabled_plugins: If provided, only activate requirements whose plugin names are in this set.
                    If None, loads all discovered requirements (used during schema init).
    :return:
    """
    from solveig import SolveigConfig

    if REQUIREMENTS._all_requirements:
        enabled_plugins = enabled_plugins or set()
        if isinstance(enabled_plugins, SolveigConfig):
            enabled_plugins = set(enabled_plugins.plugins.keys())
        with interface.with_group(
            "Filtering requirement plugins", count=len(enabled_plugins)
        ):
            # Clear current requirements and rebuild from registry
            REQUIREMENTS.registered.clear()

            interface.current_level += 1
            for req_name, req_class in REQUIREMENTS._all_requirements.items():
                module = req_class.__module__

                # Core requirements (from schema.requirements) are always enabled
                if "schema.requirements" in module:
                    REQUIREMENTS.registered[req_name] = req_class
                else:
                    # Plugin requirements are filtered by config
                    plugin_name = _get_plugin_name_from_class(req_class)
                    if plugin_name in enabled_plugins:
                        REQUIREMENTS.registered[req_name] = req_class
                    else:
                        interface.show(
                            f"≫ Skipping requirement plugin, not present in config: {plugin_name}.{req_name}"
                        )
            interface.current_level -= 1

            total_requirements = len(REQUIREMENTS.registered)
            interface.show(
                f"🕮  Requirement filtering complete: {len(enabled_plugins)} plugins, {total_requirements} requirements active"
            )

            # No need to rebuild LLMMessage - run.py uses get_filtered_llm_message_class()
            # which dynamically creates the correct schema based on current filtering
            return


def get_all_requirements() -> dict[str, type["Requirement"]]:
    """Get all registered requirement types for use by the system."""
    return REQUIREMENTS.registered.copy()


# Expose the essential interface
__all__ = [
    "REQUIREMENTS",
    "register_requirement",
    "register_plugin_result",
    "load_requirements",
    "filter_requirements",
    "get_all_requirements",
]
