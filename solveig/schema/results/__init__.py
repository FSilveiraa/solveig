"""Results module - response types for requirement operations."""

from .base import RequirementResult
from .command import CommandResult
from .copy import CopyResult
from .delete import DeleteResult
from .move import MoveResult
from .read import ReadResult
from .write import WriteResult

__all__ = [
    "RequirementResult",
    "ReadResult",
    "WriteResult",
    "CommandResult",
    "MoveResult",
    "CopyResult",
    "DeleteResult",
]
