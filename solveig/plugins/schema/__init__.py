"""Requirement plugins - new operation types that extend Solveig's capabilities."""

import importlib
import pkgutil

from solveig.config import SolveigConfig
from solveig.interface import CLIInterface, SolveigInterface

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


def load_extra_requirements(interface: SolveigInterface):
    """
    Discover and load requirement plugin files in the requirements directory.
    Similar to hooks.load_hooks() but for requirement types.
    """
    import sys
    # See note above
    from solveig.schema import REQUIREMENTS

    total_files = 0
    total_requirements = 0

    with interface.with_group("Requirement Plugins"):
        for _, module_name, is_pkg in pkgutil.iter_modules(__path__, __name__ + "."):
            if not is_pkg and not module_name.endswith(".__init__"):
                total_files += 1
                plugin_name = module_name.split(".")[-1]

                try:
                    # Get the keys that existed before loading this module
                    before_keys = list(REQUIREMENTS.all_requirements.keys())

                    # Import the module
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
    # See note above
    from solveig.schema import REQUIREMENTS

    if REQUIREMENTS.all_requirements:
        enabled_plugins = enabled_plugins or set()
        if isinstance(enabled_plugins, SolveigConfig):
            enabled_plugins = set(enabled_plugins.plugins.keys())
        with interface.with_group(
            "Filtering requirement plugins", count=len(enabled_plugins)
        ):
            # Clear current requirements and rebuild from registry
            REQUIREMENTS.registered.clear()

            interface.current_level += 1
            for req_name, req_class in REQUIREMENTS.all_requirements.items():
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


def clear_requirements():
    # See note above
    from solveig.schema import REQUIREMENTS
    REQUIREMENTS.registered.clear()
    REQUIREMENTS.all_requirements.clear()


# Expose the essential interface
__all__ = [
    "load_extra_requirements",
    "filter_requirements",
]
