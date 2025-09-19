"""
Plugin system for Solveig.

This module provides the extensible plugin architecture that allows
for validation hooks and processing plugins to be added to the system.
Currently supports:
- @before hooks: Execute before requirement processing
- @after hooks: Execute after requirement processing
"""

from .. import SolveigConfig
from ..interface import SolveigInterface
from ..exceptions import PluginException, ProcessingError, SecurityError, ValidationError
from . import hooks, schema as plugin_schema


def initialize_plugins(config: SolveigConfig, interface: SolveigInterface):
    """
    Initialize plugins with optional config filtering.

    Args:
        config: SolveigConfig instance or set of plugin names to enable
        interface: Interface for displaying plugin loading messages

    This should be called explicitly by the main application, not on import.
    It's also important that it happens here and not in the plugins
    """
    # from . import hooks, schema

    # Load plugin requirements and hooks
    plugin_schema.load_extra_requirements(interface=interface)
    hooks.load_requirement_hooks(interface=interface)

    # Filter based on config if provided
    if config is not None:
        plugin_schema.filter_requirements(interface=interface, enabled_plugins=config)
        hooks.filter_hooks(interface=interface, enabled_plugins=config)


def clear_plugins():
    hooks.clear_hooks()
    plugin_schema.clear_requirements()


__all__ = [
    "initialize_plugins",
    "clear_plugins",
    "PluginException",
    "ValidationError",
    "ProcessingError",
    "SecurityError",
]
