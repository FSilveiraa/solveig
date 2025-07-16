from pydantic import BaseModel
from pathlib import Path
from typing import Literal, Union



# Base class for things the LLM can request
class Requirement(BaseModel):
    type: str
    comment: str

    def is_possible(self, config) -> bool:
        raise NotImplementedError()


class FileRequirement(Requirement):
    path: str

    def is_possible(self, config) -> bool:
        possible = False
        negator = False
        for path in config.allowed_paths:
            # TODO: make the `path` variable itself be a Path instead of str
            if Path(self.path).is_relative_to(path):
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
    requirement: Union[FileReadRequirement|FileMetadataRequirement|CommandRequirement]

    def to_openai(self):
        return self.model_dump()


class FileReadResult(RequirementResult):
    content: str

    def to_openai(self):
        data = super().to_openai()
        requirement = data.pop("requirement")
        data["path"] = requirement["path"]
        return data


class FileMetadataResult(RequirementResult):
    content: str


class CommandResult(RequirementResult):
    stdout: str
    stderr: str

    def to_openai(self):
        data = super().to_openai()
        requirement = data.pop("requirement")
        data["command"] = requirement["command"]
        return data
