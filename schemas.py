from pydantic import BaseModel
from pathlib import Path
from typing import List, Optional, Literal, Union


class Request(BaseModel):
    prompt: str
    available_paths: List[Path]  # using str for easier JSON handling


# Base class for things the LLM can request
class Requirement(BaseModel):
    type: str


class FileRequirement(Requirement):
    type: Literal["file"]
    location: str
    comment: Optional[str]


class CommandRequirement(Requirement):
    type: Literal["command"]
    command: str
    comment: Optional[str]


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
