"""ToolReturn construction, and structured metadata models for accepted tool calls.

`accepted()`/`declined()`/`failed()` centralize how tool functions build a
`pydantic_ai.messages.ToolReturn` - `declined` and `failed` just format the
return_value text, `accepted` also takes an optional `metadata` payload.

Metadata is carried via `ToolReturn.metadata` - not sent to the LLM, but
readable by wrapper toolsets (hooks). Only tools with a real metadata
consumer get one of these; the rest just call `accepted(value)` with no
metadata. `HttpResult` exists because `trafilatura` (a WrapperToolset around
`http`) needs the response headers/body to decide whether to convert HTML
to markdown.
"""

from typing import Any

from pydantic_ai.messages import ToolReturn

from .http import HttpResult


def accepted(value: Any, metadata: Any = None) -> ToolReturn:
    """The operation completed and its result is being sent to the assistant."""
    return ToolReturn(return_value=value, metadata=metadata)


def declined(reason: str) -> ToolReturn:
    """The user declined the operation (or part of it)."""
    return ToolReturn(return_value=reason)


def failed(error: str | Exception) -> ToolReturn:
    """The operation could not be completed."""
    return ToolReturn(return_value=f"Error: {error}")


__all__ = [
    "HttpResult",
    "accepted",
    "declined",
    "failed",
]
