from __future__ import annotations

from typing import TYPE_CHECKING, List, Literal, Optional, Union

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
    requirement: Optional[Union[ReadRequirement, WriteRequirement, CommandRequirement]]
    accepted: bool
    error: Optional[str] = None

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
    metadata: Optional[dict] = None
    # For files
    content: Optional[str] = None
    content_encoding: Optional[Literal["text", "base64"]] = None
    # For directories
    directory_listing: Optional[List[dict]] = None


class WriteResult(FileResult):
    pass


class CommandResult(RequirementResult):
    success: Optional[bool] = None
    stdout: Optional[str] = None
    # use the `error` field for stderr

    def to_openai(self):
        data = super().to_openai()
        requirement = data.pop("requirement")
        data["command"] = requirement["command"]
        return data
