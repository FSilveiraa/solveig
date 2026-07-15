"""
Domain exception classes for Solveig.

These are core domain exceptions used throughout the system by both
core tools and plugins. They represent validation failures,
processing errors, and security issues.
"""


class UserCancel(Exception):
    """Event signaling the user decided to cancel processing"""

    pass


class PluginException(Exception):
    """Base exception for all plugin-related errors."""

    pass


class ValidationError(PluginException):
    """
    Raised when validation fails.
    Used by before hooks to indicate a tools should not proceed.
    """

    pass


class SecurityError(ValidationError):
    """
    Raised when a security issue is detected.
    Special case of validation error for dangerous operations.
    """

    pass
