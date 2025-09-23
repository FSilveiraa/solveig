"""
Plugin system for Solveig.

This module provides the extensible plugin architecture that allows
for validation hooks and processing plugins to be added to the system.
Currently supports:
- @before hooks: Execute before requirement processing
- @after hooks: Execute after requirement processing
"""

from .. import SolveigConfig
from ..exceptions import (
    PluginException,
    ProcessingError,
    SecurityError,
    ValidationError,
)
from ..interface import SolveigInterface
from . import hooks
from . import schema as plugin_schema


def initialize_plugins(config: SolveigConfig, interface: SolveigInterface):
    """
    Initialize plugins with optional config filtering.

    Args:
        config: SolveigConfig instance or set of plugin names to enable
        interface: Interface for displaying plugin loading messages

    This should be called explicitly by the main application, not on import.
    It's also important that it happens here and not in the plugins
    """
    with interface.with_group("Plugins"):
        # Load and filter requirements
        with interface.with_group("Requirements"):
            req_stats = plugin_schema.load_and_filter_requirements(
                interface=interface, enabled_plugins=config
            )

        with interface.with_group("Hooks"):
            # Load and filter hooks
            hook_stats = hooks.load_and_filter_hooks(
                interface=interface, enabled_plugins=config
            )

        # Summary
        interface.display_text(
            f"Plugin system ready: {req_stats['active']} requirements, {hook_stats['active']} hooks"
        )


def clear_plugins():
    hooks.clear_hooks()
    # Clear requirements directly from schema registry
    from solveig.schema import REQUIREMENTS

    REQUIREMENTS.clear_requirements()


__all__ = [
    "initialize_plugins",
    "clear_plugins",
    "PluginException",
    "ValidationError",
    "ProcessingError",
    "SecurityError",
]
