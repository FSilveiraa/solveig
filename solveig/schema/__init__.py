"""
Schema definitions for Solveig's structured communication with LLMs.

This module defines the data structures used for:
- Messages exchanged between user, LLM, and system
- Requirements (file operations, shell commands)
- Results and error handling
"""

from .requirements import (  # noqa: F401
    CommandRequirement,
    CopyRequirement,
    DeleteRequirement,
    MoveRequirement,
    ReadRequirement,
    Requirement,
    TaskListRequirement,
    WriteRequirement,
)
from .results import (  # noqa: F401
    CommandResult,
    CopyResult,
    DeleteResult,
    MoveResult,
    ReadResult,
    RequirementResult,
    TaskListResult,
    WriteResult,
)

CORE_REQUIREMENTS: list[type[Requirement]] = [
    CommandRequirement,
    CopyRequirement,
    DeleteRequirement,
    MoveRequirement,
    ReadRequirement,
    TaskListRequirement,
    WriteRequirement,
]

CORE_RESULTS: list[type[RequirementResult]] = [
    ReadResult,
    WriteResult,
    CommandResult,
    MoveResult,
    CopyResult,
    DeleteResult,
    TaskListResult,
    RequirementResult,
]


# Rebuild Pydantic models to resolve forward references
# Order matters: requirements first, then results that reference them
for requirement in CORE_REQUIREMENTS:
    requirement.model_rebuild()

for result in CORE_RESULTS:
    result.model_rebuild()


class REQUIREMENTS:
    """Registry for dynamically discovered requirement plugins."""

    registered: dict[str, type["Requirement"]] = {}
    all_requirements: dict[str, type["Requirement"]] = {}

    def __new__(cls, *args, **kwargs):
        raise TypeError("REQUIREMENTS is a static registry and cannot be instantiated")

    @classmethod
    def register_requirement(cls, requirement_class: type["Requirement"]):
        """
        Register any requirement class (core or plugin).
        Single unified registration method.
        """
        cls.all_requirements[requirement_class.__name__] = requirement_class
        cls.registered[requirement_class.__name__] = requirement_class
        return requirement_class

    @classmethod
    def clear_requirements(cls):
        """Clear all registered requirements (used by tests)."""
        cls.registered.clear()
        cls.all_requirements.clear()


# Initialize with core requirements using the list
for requirement in CORE_REQUIREMENTS:
    REQUIREMENTS.register_requirement(requirement)

# Export the registration decorator for direct use
register_requirement = REQUIREMENTS.register_requirement

__all__ = ["REQUIREMENTS", "CORE_REQUIREMENTS", "register_requirement"]
