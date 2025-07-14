from pydantic import BaseModel, TypeAdapter
from pathlib import Path
from typing import List, Optional, Literal, Union


class Request(BaseModel):
    user_prompt: str


# Base class for things the LLM can request
class Requirement(BaseModel):
    type: str
    comment: str

    def is_possible(self, config) -> bool:
        raise NotImplementedError()


class FileRequirement(Requirement):
    location: str

    def is_possible(self, config) -> bool:
        possible = False
        negator = False
        for path in config.allowed_paths:
            # TODO: make the `location` variable itself be a Path instead of str
            if Path(self.location).is_relative_to(path):
                if self.mode_allowed(path.mode):
                    possible = True
                elif path.mode == "n":
                    negator = True
        return possible and not negator

    @staticmethod
    def mode_allowed(mode: str) -> bool:
        raise NotImplementedError()


class FileReadRequirement(FileRequirement):
    type: Literal["read"] = "read"

    @staticmethod
    def mode_allowed(mode: str) -> bool:
        return mode in {"r", "w"}


class FileMetadataRequirement(FileRequirement):
    type: Literal["metadata"] = "metadata"

    @staticmethod
    def mode_allowed(mode: str) -> bool:
        return mode in {"m", "r", "w"}


class CommandRequirement(Requirement):
    type: Literal["command"] = "command"
    command: str


# Base class for data returned for requirements
class RequirementResult(BaseModel):
    requirement: Requirement


class FileResult(RequirementResult):
    content: str


class CommandResult(RequirementResult):
    output: str


# The LLM's response can be:
# - either a list of Requirements asking for more info
# - or a response with the final answer
class Response(BaseModel):
    type: Literal["response"] = "response"
    comment: Optional[str] = None
    requirements: Optional[List[FileReadRequirement|FileMetadataRequirement|CommandRequirement]] = None
