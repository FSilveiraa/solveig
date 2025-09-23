"""Requirement plugins - new operation types that extend Solveig's capabilities."""

import importlib
import pkgutil

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface

"""
Note on local imports: this is required to fix a circular import error.

Requirements and the Plugins system rely on each other. requirements/base.py has to import plugins so
they can run hooks, and plugins/schema/__init__.py (this file) has to import
requirements/__init__.py::REQUIREMENTS so it can register plugin requirements on it, creating an import loop.
It's also important to stress that the ordering of all this matters: we need to first load core schema
requirements, then plugin requirements, then finally hooks. Currently this is done by just importing
solveig.schema (which runs REQUIREMENTS.register_core_requirements()), then run.py calls
plugins/__init__.py::initialize_plugins() which in turn first loads the extra requirements (here), then
loads the hooks, then filters both in the same order.
Both the loading and filtering of extra requirements do a local import of the central REQUIREMENTS registry.
Any alternative solution I can think of that attempts to break this involves either a convoluted 3rd layer
that joins  requirements+hooks and runs the whole thing (aka requirements no longer run hooks themselves),
or registering plugin requirements separately and having message.py join them, and the order above still
has to be maintained.

This doesn't mean core requirements or core solveig code relies on individual plugins.
It means the CORE Requirements system relies on the CORE Plugins system, and vice-versa.
"""


def _get_plugin_name_from_class(cls: type) -> str:
    """Extract plugin name from class module path."""
    module = cls.__module__
    if ".requirements." in module:
        # Extract plugin name from module path like 'solveig.plugins.requirements.tree'
        return module.split(".requirements.")[-1]
    return "unknown"


def load_and_filter_requirements(
    interface: SolveigInterface,
    enabled_plugins: set[str] | SolveigConfig | None,
    allow_all: bool = False,
) -> dict[str, int]:
    """
    Discover, load, and filter requirement plugins in one step.
    Returns statistics dictionary.
    """
    import sys

    from solveig.schema import REQUIREMENTS

    # Store core requirements before clearing
    core_requirements = {}
    for name, req_class in REQUIREMENTS.all_requirements.items():
        if "schema.requirements" in req_class.__module__:
            core_requirements[name] = req_class

    # Clear and restore core requirements
    REQUIREMENTS.all_requirements.clear()
    REQUIREMENTS.registered.clear()
    REQUIREMENTS.all_requirements.update(core_requirements)
    REQUIREMENTS.registered.update(core_requirements)  # Core requirements always active

    # Convert config to plugin set
    if isinstance(enabled_plugins, SolveigConfig):
        enabled_plugins = set(enabled_plugins.plugins.keys())

    loaded_plugins = 0
    active_plugins = 0

    # Load all requirement plugins
    for _, module_name, is_pkg in pkgutil.iter_modules(__path__, __name__ + "."):
        if not is_pkg and not module_name.endswith(".__init__"):
            plugin_name = module_name.split(".")[-1]

            try:
                before_keys = set(REQUIREMENTS.all_requirements.keys())

                # Import/reload module
                if module_name in sys.modules:
                    importlib.reload(sys.modules[module_name])
                else:
                    importlib.import_module(module_name)

                # Find newly added requirements
                new_requirement_names = [
                    name
                    for name in REQUIREMENTS.all_requirements.keys()
                    if name not in before_keys
                ]

                if new_requirement_names:
                    loaded_plugins += 1

                    # Filter - add to active if enabled
                    if allow_all or (
                        enabled_plugins and plugin_name in enabled_plugins
                    ):
                        for req_name in new_requirement_names:
                            req_class = REQUIREMENTS.all_requirements[req_name]
                            REQUIREMENTS.registered[req_name] = req_class
                        active_plugins += 1
                        interface.display_text(f"'{plugin_name}': Loaded")
                    else:
                        interface.display_warning(
                            f"'{plugin_name}': Skipped (missing from config)"
                        )

            except Exception as e:
                interface.display_error(
                    f"Requirement plugin {module_name}.{plugin_name}: {e}"
                )

    total_active = len(REQUIREMENTS.registered)
    interface.display_text(
        f"Requirements: {len(core_requirements)} core, {loaded_plugins} plugins ({active_plugins} active), {total_active} total"
    )

    return {"loaded": loaded_plugins, "active": total_active}


# Legacy function - kept for compatibility
def load_extra_requirements(interface: SolveigInterface):
    """Legacy function - use load_and_filter_requirements instead."""
    return load_and_filter_requirements(interface, None)


def filter_requirements(
    interface: SolveigInterface, enabled_plugins: set[str] | SolveigConfig | None = None
):
    """Legacy function - use load_and_filter_requirements instead."""
    return load_and_filter_requirements(interface, enabled_plugins)


def register_requirement(requirement_class):
    """
    Decorator to register a requirement plugin.

    Usage:
    @register_requirement
    class MyRequirement(Requirement):
        ...
    """
    # Import here to avoid circular imports
    from solveig.schema import REQUIREMENTS
    
    return REQUIREMENTS.register_requirement(requirement_class)


def clear_requirements():
    # Import here to avoid circular imports
    from solveig.schema import REQUIREMENTS

    REQUIREMENTS.clear_requirements()


# Expose the essential interface
__all__ = [
    "load_and_filter_requirements",
    "load_extra_requirements",  # legacy
    "filter_requirements",  # legacy
    "register_requirement",  # decorator for plugin requirements
]
