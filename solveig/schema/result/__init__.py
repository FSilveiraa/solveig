"""Results module - response types for tool operations."""

from .base import ToolResult
from .command import CommandResult
from .copy import CopyResult
from .delete import DeleteResult
from .edit import EditResult
from .http import HttpResult
from .move import MoveResult
from .read import ReadResult
from .write import WriteResult

__all__ = [
    "ToolResult",
    "ReadResult",
    "WriteResult",
    "EditResult",
    "CommandResult",
    "HttpResult",
    "MoveResult",
    "CopyResult",
    "DeleteResult",
]
