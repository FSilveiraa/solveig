"""
Exception classes for plugin validation and processing.
Plugins raise these exceptions to signal validation failures or processing errors.
The requirement layer catches these and wraps them into appropriate result objects.
"""


class PluginException(Exception):
    """Base exception for all plugin-related errors."""

    pass


class ValidationError(PluginException):
    """
    Raised when a plugin validation fails.
    Used by before hooks to indicate a requirement should not proceed.
    """

    pass


class ProcessingError(PluginException):
    """
    Raised when a plugin post-processing operation fails.
    Used by after hooks to indicate result processing failed.
    """

    pass


class SecurityError(ValidationError):
    """
    Raised when a plugin detects a security issue.
    Special case of validation error for dangerous operations.
    """

    pass
