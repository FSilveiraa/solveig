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
    TaskListRequirement,
)
from .results import (  # noqa: F401
    CommandResult,
    CopyResult,
    DeleteResult,
    MoveResult,
    ReadResult,
    RequirementResult,
    WriteResult,
    TaskResult,
)

# Rebuild Pydantic models to resolve forward references
# This must be done after all classes are defined to fix circular import issues
ReadResult.model_rebuild()
WriteResult.model_rebuild()
CommandResult.model_rebuild()
MoveResult.model_rebuild()
CopyResult.model_rebuild()
DeleteResult.model_rebuild()
TaskResult.model_rebuild()
RequirementResult.model_rebuild()


class REQUIREMENTS:
    """Registry for dynamically discovered requirement plugins."""

    registered: dict[str, type["Requirement"]] = {}
    all_requirements: dict[str, type["Requirement"]] = {}

    def __new__(cls, *args, **kwargs):
        raise TypeError("REQUIREMENTS is a static registry and cannot be instantiated")

    @classmethod
    def register_requirement(cls, requirement_class: type["Requirement"]):
        """
        Decorator to register a requirement plugin.

        Usage:
        @register_requirement
        class MyRequirement(Requirement):
            ...
        """
        # Store in both active and all requirements registry
        REQUIREMENTS.registered[requirement_class.__name__] = requirement_class
        REQUIREMENTS.all_requirements[requirement_class.__name__] = requirement_class

        return requirement_class

    @classmethod
    def register_core_requirements(cls):
        """Register all core requirement types in the plugin registry for unified access."""
        # Core requirement classes
        core_requirements = [
            ReadRequirement,
            WriteRequirement,
            CommandRequirement,
            MoveRequirement,
            CopyRequirement,
            DeleteRequirement,
            TaskListRequirement,
        ]

        for requirement_class in core_requirements:
            # Only register if not already registered
            if requirement_class.__name__ not in cls.registered:
                cls.register_requirement(requirement_class)


REQUIREMENTS.register_core_requirements()

register_requirement = REQUIREMENTS.register_requirement
__all__ = [
    "REQUIREMENTS",
    "register_requirement"
]
