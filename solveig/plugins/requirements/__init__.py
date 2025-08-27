"""Requirement plugins - new operation types that extend Solveig's capabilities."""

import importlib
import pkgutil
from typing import Dict, Type

from solveig.interface import CLIInterface, SolveigInterface


class REQUIREMENTS:
    """Registry for dynamically discovered requirement plugins."""
    
    registered: Dict[str, Type] = {}
    _all_requirements: Dict[str, Type] = {}
    
    def __new__(cls, *args, **kwargs):
        raise TypeError("REQUIREMENTS is a static registry and cannot be instantiated")


def register_requirement(requirement_class: Type):
    """
    Decorator to register a requirement plugin.
    
    Usage:
    @register_requirement
    class MyRequirement(Requirement):
        ...
    """
    plugin_name = _get_plugin_name_from_class(requirement_class)
    
    # Store in both active and all requirements registry
    REQUIREMENTS.registered[requirement_class.__name__] = requirement_class
    REQUIREMENTS._all_requirements[requirement_class.__name__] = requirement_class
    
    return requirement_class


def _get_plugin_name_from_class(cls: Type) -> str:
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
                current_count = len(REQUIREMENTS._all_requirements)
                
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
                        name for name in REQUIREMENTS._all_requirements.keys() 
                        if name not in before_keys
                    ]
                    
                    if new_requirement_names:
                        total_requirements += len(new_requirement_names)
                        for req_name in new_requirement_names:
                            interface.show(f"✓ Loaded requirement from {plugin_name}.{req_name}")
                    else:
                        interface.show(f"≫ Plugin {plugin_name} loaded but registered no requirements")
                        
                except Exception as e:
                    interface.display_error(f"Failed to load requirement plugin {plugin_name}: {e}")
        
        interface.show(
            f"🕮  Requirement plugin loading complete: {total_files} files, {total_requirements} requirements"
        )


def get_all_requirements() -> Dict[str, Type]:
    """Get all registered requirement types for use by the system."""
    return REQUIREMENTS.registered.copy()


# Expose the essential interface
__all__ = ["REQUIREMENTS", "register_requirement", "load_requirements", "get_all_requirements"]