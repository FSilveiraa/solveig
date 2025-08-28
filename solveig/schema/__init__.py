"""
Schema definitions for Solveig's structured communication with LLMs.

This module defines the data structures used for:
- Messages exchanged between user, LLM, and system
- Requirements (file operations, shell commands)
- Results and error handling
"""

from .message import LLMMessage, MessageHistory, UserMessage  # noqa: F401
from .requirements import (  # noqa: F401
    CommandRequirement,
    CopyRequirement,
    DeleteRequirement,
    MoveRequirement,
    ReadRequirement,
    Requirement,
    WriteRequirement,
)
from .results import (  # noqa: F401
    CommandResult,
    CopyResult,
    DeleteResult,
    MoveResult,
    ReadResult,
    RequirementResult,
    WriteResult,
)

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


# Register core requirements in the unified registry
def _register_core_requirements():
    """Register all core requirement types in the plugin registry for unified access."""
    from ..plugins.requirements import REQUIREMENTS, register_requirement

    # Core requirement classes
    core_requirements = [
        ReadRequirement,
        WriteRequirement,
        CommandRequirement,
        MoveRequirement,
        CopyRequirement,
        DeleteRequirement,
    ]

    for requirement_class in core_requirements:
        # Only register if not already registered
        if requirement_class.__name__ not in REQUIREMENTS.registered:
            register_requirement(requirement_class)


_register_core_requirements()

# Load plugin requirements and hooks
plugins.requirements.load_requirements()
plugins.hooks.load_hooks()
