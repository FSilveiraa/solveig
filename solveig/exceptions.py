"""
Domain exception classes for Solveig.

These are core domain exceptions used throughout the system by both
core requirements and plugins. They represent validation failures,
processing errors, and security issues.
"""


class PluginException(Exception):
    """Base exception for all plugin-related errors."""

    pass


class ValidationError(PluginException):
    """
    Raised when validation fails.
    Used by before hooks to indicate a requirement should not proceed.
    """

    pass


class ProcessingError(PluginException):
    """
    Raised when post-processing operation fails.
    Used by after hooks to indicate result processing failed.
    """

    pass


class SecurityError(ValidationError):
    """
    Raised when a security issue is detected.
    Special case of validation error for dangerous operations.
    """

    pass
