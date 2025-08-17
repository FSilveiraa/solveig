from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from ..utils.file import Metadata

# Circular import fix:
# - This module (result.py) needs Requirement classes for type hints
# - requirement.py imports Result classes for actual usage
# - TYPE_CHECKING solves this: imports are only loaded during type checking,
#   not at runtime, breaking the circular dependency
if TYPE_CHECKING:
    from .requirement import (
        CommandRequirement,
        CopyRequirement,
        DeleteRequirement,
        MoveRequirement,
        ReadRequirement,
        WriteRequirement,
    )


# Base class for data returned for requirements
class RequirementResult(BaseModel):
    # we store the initial requirement for debugging/error printing,
    # then when JSON'ing we usually keep a couple of its fields in the result's body
    # We keep paths separately from the requirement, since we want to preserve both the path(s) the LLM provided
    # and their absolute value (~/Documents vs /home/jdoe/Documents)
    requirement: (
        ReadRequirement
        | WriteRequirement
        | CommandRequirement
        | MoveRequirement
        | CopyRequirement
        | DeleteRequirement
        | None
    )
    accepted: bool
    error: str | None = None

    def to_openai(self):
        data = self.model_dump()
        data.pop("requirement")
        # convert all Paths to str when serializing
        data = {
            key: str(value) if isinstance(value, Path) else value
            for key, value in data.items()
        }
        # if data.get("metadata"):
        #     data["metadata"]["path"] = str(data["metadata"]["path"])
        return data


class ReadResult(RequirementResult):
    path: str | Path
    metadata: Metadata | None = None
    # For files
    content: str | None = None
    # For directories
    directory_listing: dict[Path, Metadata] | None = None

    def to_openai(self):
        data = super().to_openai()
        if data.get("directory_listing"):
            data["directory_listing"] = {
                str(path): metadata
                for path, metadata in data["directory_listing"].items()
            }
        return data


class WriteResult(RequirementResult):
    path: str | Path


class MoveResult(RequirementResult):
    source_path: str | Path
    destination_path: str | Path


class CopyResult(RequirementResult):
    source_path: str | Path
    destination_path: str | Path


class DeleteResult(RequirementResult):
    path: str | Path


class CommandResult(RequirementResult):
    command: str
    success: bool | None = None
    stdout: str | None = None
