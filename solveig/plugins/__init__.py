"""
Plugin system for Solveig.

This module provides the extensible plugin architecture that allows
for validation hooks and processing plugins to be added to the system.
Currently supports:
- @before hooks: Execute before requirement processing
- @after hooks: Execute after requirement processing
"""

from . import hooks, requirements
from .exceptions import PluginException, ProcessingError, SecurityError, ValidationError

__all__ = [
    "hooks",
    "requirements",
    "PluginException",
    "ValidationError",
    "ProcessingError",
    "SecurityError",
]
