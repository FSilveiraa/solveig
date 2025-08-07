from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

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
        return data

    # def to_openai(self):
    #     return self.model_dump()


# class FileResult(RequirementResult):
# hack to preserve the paths
# def to_openai(self):
#     data = super().to_openai()
#     requirement = data.pop("requirement")
#     # for attr in { "path", "source_path", "destination_path" }:
#     #     if attr in requirement:
#     #         data[attr] = requirement[attr]
#     return data


class ReadResult(RequirementResult):
    path: str | Path
    metadata: dict | None = None
    # For files
    content: str | None = None
    content_encoding: Literal["text", "base64"] | None = None
    # For directories
    directory_listing: list[dict] | None = None


class WriteResult(RequirementResult):
    path: str | Path


class MoveResult(RequirementResult):
    source_path: str | Path
    destination_path: str | Path
    # def to_openai(self):
    #     data = super().to_openai()
    #     requirement = data.pop("requirement")
    #     data["source_path"] = requirement["source_path"]
    #     data["dest_path"] = requirement["dest_path"]
    #     return data


class CopyResult(RequirementResult):
    source_path: str | Path
    destination_path: str | Path
    # def to_openai(self):
    #     data = super().to_openai()
    #     requirement = data.pop("requirement")
    #     data["source_path"] = requirement["source_path"]
    #     data["dest_path"] = requirement["dest_path"]
    #     return data


class DeleteResult(RequirementResult):
    path: str | Path
    # def to_openai(self):
    #     data = super().to_openai()
    #     requirement = data.pop("requirement")
    #     data["path"] = requirement["path"]
    #     return data


class CommandResult(RequirementResult):
    command: str
    success: bool | None = None
    stdout: str | None = None
    # use the `error` field for stderr

    # def to_openai(self):
    #     data = super().to_openai()
    #     requirement = data.pop("requirement")
    #     data["command"] = requirement["command"]
    #     return data
