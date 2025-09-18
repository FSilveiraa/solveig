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
from . import hooks, schema
from .exceptions import PluginException, ProcessingError, SecurityError, ValidationError


def initialize_plugins(config: SolveigConfig, interface: SolveigInterface):
    """
    Initialize plugins with optional config filtering.

    Args:
        config: SolveigConfig instance or set of plugin names to enable
        interface: Interface for displaying plugin loading messages

    This should be called explicitly by the main application, not on import.
    It's also important that it happens here and not in the plugins
    """
    from . import hooks, schema

    # Load plugin requirements and hooks
    schema.load_requirements(interface=interface)
    hooks.load_hooks(interface=interface)

    # Filter based on config if provided
    if config is not None:
        schema.filter_requirements(interface=interface, enabled_plugins=config)
        hooks.filter_hooks(interface=interface, enabled_plugins=config)


def clear_plugins():
    hooks.HOOKS.before.clear()
    hooks.HOOKS.after.clear()
    hooks.HOOKS._all_hooks.clear()
    schema.REQUIREMENTS.registered.clear()
    schema.REQUIREMENTS.all_requirements.clear()


__all__ = [
    "initialize_plugins",
    "clear_plugins",
    "hooks",
    "schema",
    "PluginException",
    "ValidationError",
    "ProcessingError",
    "SecurityError",
]
