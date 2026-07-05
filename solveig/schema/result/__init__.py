"""Structured metadata models for accepted tool calls.

Carried via `pydantic_ai.messages.ToolReturn.metadata` - not sent to the LLM,
but readable by wrapper toolsets (hooks) and later session-replay display.
"""

from .command import CommandResult
from .copy import CopyResult
from .delete import DeleteResult
from .edit import EditResult
from .http import HttpResult
from .move import MoveResult
from .read import ReadResult
from .write import WriteResult

__all__ = [
    "ReadResult",
    "WriteResult",
    "EditResult",
    "CommandResult",
    "HttpResult",
    "MoveResult",
    "CopyResult",
    "DeleteResult",
]
