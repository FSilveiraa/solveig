from __future__ import annotations

import subprocess
from pydantic import BaseModel, field_validator
from pathlib import Path
from typing import Literal, Union, Optional

from config import SolveigConfig


YES = { "y", "yes" }
TRUNCATE_JOIN = "(...)"


def truncate_output(content: str, max_size: int) -> str:
    content_to_print = content
    if len(content) > max_size:
        size_of_each_side = int((max_size - len(TRUNCATE_JOIN)) / 2)
        content_to_print = content[:size_of_each_side] + TRUNCATE_JOIN + content[size_of_each_side:]
    return content_to_print


# Base class for things the LLM can request
class Requirement(BaseModel):
    type: str
    comment: str

    @field_validator("comment", mode="before")
    @classmethod
    def strip_name(cls, comment):
        return comment.strip()

    def solve(self, config) -> RequirementResult:
        raise NotImplementedError()


class FileRequirement(Requirement):
    path: str

    def is_possible(self, config: SolveigConfig) -> bool:
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

    def solve(self, config) -> FileReadResult|None:
        print("  [ File ]")
        print(f"    {self.comment}")
        print(f"      path: {self.path}")
        if input("  ? Allow reading file? [y/N]: ").strip().lower() in YES:
            with open(self.path, "r") as fd:
                content = fd.read()
            print("    [ Content ]")
            print("      " + truncate_output(content, config.max_file_output))
            if input("  ? Allow sending file data? [y/N]: ").strip().lower() in YES:
                return FileReadResult(requirement=self, content=content)


class FileMetadataRequirement(FileRequirement):
    type: Literal["metadata"] = "metadata"

    @staticmethod
    def mode_allowed(mode: str) -> bool:
        return mode in {"m", "r", "w"}

    def solve(self, config) -> FileMetadataResult|None:
        return None


class CommandRequirement(Requirement):
    type: Literal["command"] = "command"
    command: str

    def solve(self, config) -> CommandResult|None:
        print(f"  [ Command ]")
        print(f"    {self.comment}")
        print(f"      command: {self.command}")
        #print(f"    (type={self.type}, command='{self.command}')")
        if input("    ? Allow running command? [y/N]: ").strip().lower() in YES:
            success = False
            try:
                result = subprocess.run(self.command, shell=True, capture_output=True, text=True, timeout=10)
                output = result.stdout.strip()
                error = result.stderr.strip() if result.stderr else ""
                success = True
            except Exception as e:
                output = None
                error = str(e)
                print(error)

            print("    [ Output ]")
            print("      " + truncate_output(output, config.max_file_output))
            if error:
                print("    [ Error ]")
                print("      " + truncate_output(error, config.max_file_output))
            if input("    ? Allow sending output? [y/N]: ").strip().lower() in YES:
                return CommandResult(requirement=self, stdout=output, stderr=error, success=success)


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
    success: bool
    stdout: Optional[str] = None
    stderr: Optional[str] = None

    def to_openai(self):
        data = super().to_openai()
        requirement = data.pop("requirement")
        data["command"] = requirement["command"]
        return data
