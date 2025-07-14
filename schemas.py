import pathlib

from pydantic import BaseModel
from pathlib import Path
from typing import List, Optional, Literal, Union

from config import SolveigConfig


class Request(BaseModel):
    prompt: str
    available_paths: List[Path]  # using str for easier JSON handling


# Base class for things the LLM can request
class Requirement(BaseModel):
    type: str
    comment: Optional[str]

    def is_possible(self, config: SolveigConfig) -> bool:
        raise NotImplementedError()


class FileRequirement(Requirement):
    location: str

    def is_possible(self, config: SolveigConfig) -> bool:
        possible = False
        negator = False
        for path, mode in config.allowed_paths:
            # TODO: make the variable itself be a Path instead of str
            if Path(self.location).is_relative_to(path):
                if self.mode_allowed(mode):
                    possible = True
                elif mode == "n":
                    negator = True
        return possible and not negator

    @staticmethod
    def mode_allowed(mode: str) -> bool:
        raise NotImplementedError()


class FileReadRequirement(FileRequirement):
    type: Literal["read"]

    @staticmethod
    def mode_allowed(mode: str) -> bool:
        return mode in {"r", "w"}


class FileMetadataRequirement(Requirement):
    type: Literal["metadata"]
    location: str

    @staticmethod
    def mode_allowed(mode: str) -> bool:
        return mode in {"m", "r", "w"}


class CommandRequirement(Requirement):
    type: Literal["command"]
    command: str


# Base class for data returned for requirements
class RequirementResult(BaseModel):
    requirement: Requirement


class FileResult(RequirementResult):
    content: str


class CommandResult(RequirementResult):
    output: str


# Final response from LLM with its answer
class FinalResponse(BaseModel):
    comment: Optional[str]
    answer: str  # The final output text or structured answer


# The LLM's response can be:
# - either a list of Requirements asking for more info
# - or a FinalResponse with the final answer
LLMResponse = Union[List[Requirement], FinalResponse]
