"""
Domain exception classes for Solveig.

These are core domain exceptions used throughout the system by both
core tools and plugins. They represent validation failures,
processing errors, and security issues.
"""


class UserCancel(Exception):
    """Event signaling the user decided to cancel processing.

    Raised at the two boundaries where a cancel becomes an ANSWER rather than a
    teardown: a prompt (`ask_question`/`ask_choice` - Esc means the user said
    "cancel") and a cancellable block (`with_cancellable` - the work did not
    happen). Both are places the caller opted into explicitly, so an ordinary
    Exception is the right shape: it is caught deliberately, not by accident.
    """

    pass


class ToolDisabledError(Exception):
    """Raised when a tool call targets a tool disabled via `tools.<name>.enabled=false`.

    Enforced once in `run_tool_and_hooks` (the seam both the LLM path and the
    `/tool` subcommand path cross), so a disabled tool is refused uniformly:
    the agent turns it into a `ModelRetry`, the subcommand into a displayed error.
    """

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
