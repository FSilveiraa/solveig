from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

# Circular import fix:
# - This module (result.py) needs Requirement classes for type hints
# - requirement.py imports Result classes for actual usage
# - TYPE_CHECKING solves this: imports are only loaded during type checking,
#   not at runtime, breaking the circular dependency
if TYPE_CHECKING:
    from .requirement import CommandRequirement, ReadRequirement, WriteRequirement


# Base class for data returned for requirements
class RequirementResult(BaseModel):
    # we store the initial requirement for debugging/error printing,
    # then when JSON'ing we usually keep a couple of its fields in the result's body
    requirement: ReadRequirement | WriteRequirement | CommandRequirement | None
    accepted: bool
    error: str | None = None

    def to_openai(self):
        return self.model_dump()


class FileResult(RequirementResult):
    # preserve the original path, the real path is in the metadata
    def to_openai(self):
        data = super().to_openai()
        requirement = data.pop("requirement")
        data["path"] = requirement["path"]
        return data


class ReadResult(FileResult):
    metadata: dict | None = None
    # For files
    content: str | None = None
    content_encoding: Literal["text", "base64"] | None = None
    # For directories
    directory_listing: list[dict] | None = None


class WriteResult(FileResult):
    pass


class CommandResult(RequirementResult):
    success: bool | None = None
    stdout: str | None = None
    # use the `error` field for stderr

    def to_openai(self):
        data = super().to_openai()
        requirement = data.pop("requirement")
        data["command"] = requirement["command"]
        return data
