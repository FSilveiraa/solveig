"""
Schema definitions for Solveig's structured communication with LLMs.

This module defines the data structures used for:
- Messages exchanged between user, LLM, and system
- Requirements (file operations, shell commands)
- Results and error handling
"""

from .message import LLMMessage, MessageHistory, UserMessage
from .requirement import (
    CommandRequirement,
    CopyRequirement,
    DeleteRequirement,
    MoveRequirement,
    ReadRequirement,
    Requirement,
    WriteRequirement,
)
from .result import (
    CommandResult,
    CopyResult,
    DeleteResult,
    MoveResult,
    ReadResult,
    RequirementResult,
    WriteResult,
)

__all__ = [
    "LLMMessage",
    "UserMessage",
    "MessageHistory",
    "Requirement",
    "ReadRequirement",
    "WriteRequirement",
    "CommandRequirement",
    "MoveRequirement",
    "CopyRequirement",
    "DeleteRequirement",
    "RequirementResult",
    "ReadResult",
    "WriteResult",
    "CommandResult",
    "MoveResult",
    "CopyResult",
    "DeleteResult",
]

# Rebuild Pydantic models to resolve forward references
# This must be done after all classes are defined to fix circular import issues
ReadResult.model_rebuild()
WriteResult.model_rebuild()
CommandResult.model_rebuild()
MoveResult.model_rebuild()
CopyResult.model_rebuild()
DeleteResult.model_rebuild()
RequirementResult.model_rebuild()

# Auto-load plugins after schema is fully initialized
from .. import plugins

plugins.hooks.load_hooks()
