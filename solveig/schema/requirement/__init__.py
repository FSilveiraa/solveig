"""Requirements module - core request types that LLMs can make."""

from .base import Requirement
from .command import CommandRequirement
from .copy import CopyRequirement
from .delete import DeleteRequirement
from .move import MoveRequirement
from .read import ReadRequirement
from .write import WriteRequirement

CORE_REQUIREMENTS: list[type[Requirement]] = [
    CommandRequirement,
    CopyRequirement,
    DeleteRequirement,
    MoveRequirement,
    ReadRequirement,
    WriteRequirement,
]

# Rebuild Pydantic models to resolve forward references
for requirement in CORE_REQUIREMENTS:
    requirement.model_rebuild()

__all__ = [
    "CORE_REQUIREMENTS",
    "Requirement",
    "ReadRequirement",
    "WriteRequirement",
    "CommandRequirement",
    "MoveRequirement",
    "CopyRequirement",
    "DeleteRequirement",
]
