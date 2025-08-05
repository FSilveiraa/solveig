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