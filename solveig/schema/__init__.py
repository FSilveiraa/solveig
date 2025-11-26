"""
Schema definitions for Solveig's structured communication with LLMs.

This module defines the data structures used for:
- Messages exchanged between user, LLM, and system
- Requirements (file operations, shell commands)
- Results and error handling
"""
# from . import REQUIREMENTS
from .requirement import (  # noqa: F401
    CommandRequirement,
    CopyRequirement,
    DeleteRequirement,
    MoveRequirement,
    ReadRequirement,
    Requirement,
    WriteRequirement,
)
from .result import (  # noqa: F401
    CommandResult,
    CopyResult,
    DeleteResult,
    MoveResult,
    ReadResult,
    RequirementResult,
    WriteResult,
)

CORE_REQUIREMENTS: list[type[Requirement]] = [
    CommandRequirement,
    CopyRequirement,
    DeleteRequirement,
    MoveRequirement,
    ReadRequirement,
    WriteRequirement,
]

CORE_RESULTS: list[type[RequirementResult]] = [
    ReadResult,
    WriteResult,
    CommandResult,
    MoveResult,
    CopyResult,
    DeleteResult,
    RequirementResult,
]


# Rebuild Pydantic models to resolve forward references
# Order matters: requirements first, then results that reference them
for requirement in CORE_REQUIREMENTS:
    requirement.model_rebuild()

for result in CORE_RESULTS:
    result.model_rebuild()

# Initialize master list with core requirements
# for requirement in CORE_REQUIREMENTS:
#     REQUIREMENTS.register(requirement)

# Export the registration decorator for direct use

__all__ = ["CORE_REQUIREMENTS", "Requirement"]
