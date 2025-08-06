"""
Schema definitions for Solveig's structured communication with LLMs.

This module defines the data structures used for:
- Messages exchanged between user, LLM, and system
- Requirements (file operations, shell commands)
- Results and error handling
"""

from .message import LLMMessage, UserMessage, MessageHistory
from .requirement import (
    Requirement,
    ReadRequirement, 
    WriteRequirement,
    CommandRequirement,
)
from .result import (
    RequirementResult,
    ReadResult,
    WriteResult, 
    CommandResult,
)

__all__ = [
    "LLMMessage",
    "UserMessage", 
    "MessageHistory",
    "Requirement",
    "ReadRequirement",
    "WriteRequirement", 
    "CommandRequirement",
    "RequirementResult",
    "ReadResult",
    "WriteResult",
    "CommandResult",
]

# Rebuild Pydantic models to resolve forward references
# This must be done after all classes are defined to fix circular import issues
ReadResult.model_rebuild()
WriteResult.model_rebuild()
CommandResult.model_rebuild()
RequirementResult.model_rebuild()

# Auto-load plugins after schema is fully initialized
from .. import plugins
plugins.hooks.load_hooks()