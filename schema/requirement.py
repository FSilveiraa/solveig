from __future__ import annotations

import json
import os.path
import subprocess

from pydantic import BaseModel, field_validator
from pathlib import Path
from typing import Literal, Union, Optional, List

from config import SolveigConfig
import utils.file
from utils.misc import ask_yes, format_output



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
    type: Literal["file"] = "file"
    path: str
    action: Literal["read", "metadata"]

    def is_possible(self, config: SolveigConfig) -> bool:
        possible = False
        negator = False
        for path in config.allowed_paths:
            if Path(self.path).is_relative_to(path):
                if self.mode_allowed(path.mode):
                    possible = True
                elif path.mode == "n":
                    negator = True
        return possible and not negator

    @staticmethod
    def mode_allowed(mode: str) -> bool:
        raise NotImplementedError()

    def solve(self, config) -> FileResult|None:
        abs_path = os.path.abspath(os.path.expanduser(self.path))
        exists = os.path.exists(abs_path)
        is_dir = os.path.isdir(abs_path)

        print("  [ File ]")
        print(f"    {self.comment}")
        print(f"      path: {self.path} (dir={is_dir})")

        if not exists:
            print("    This path does not exist.")

        else:
            if is_dir:
                if ask_yes("    ? Allow reading directory listing and metadata? [y/N] "):
                    metadata, entries = utils.file.read_metadata_and_entries(abs_path)
                    return FileResult(requirement=self, metadata=metadata, directory_listing=entries)
            else:
                choice_read_file = input("    ? Read file? [y=contents+metadata / m=metadata / N=skip]: ").strip().lower()
                if choice_read_file in { "m", "y" }:
                    print("    [ Metadata ]")
                    content = None
                    metadata, _ = utils.file.read_metadata_and_entries(abs_path)
                    print(format_output(json.dumps(metadata), indent=4, max_lines=config.max_output_lines, max_chars=config.max_output_size))
                    if choice_read_file == "y":
                        content, encoding = utils.file.read_file(abs_path)
                        print("    [ Content ]")
                        print("      " + ("(Base64)" if encoding == "base64" else format_output(content, indent=6, max_lines=config.max_output_lines, max_chars=config.max_output_size)))
                    if ask_yes("    ? Allow sending file data? [y/N]: "):
                        return FileResult(requirement=self, metadata=metadata, content=content)


class CommandRequirement(Requirement):
    type: Literal["command"] = "command"
    command: str

    def solve(self, config) -> CommandResult|None:
        print(f"  [ Command ]")
        print(f"    {self.comment}")
        print(f"      command: {self.command}")
        #print(f"    (type={self.type}, command='{self.command}')")
        if ask_yes("    ? Allow running command? [y/N]: "):
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
            print(format_output(output, indent=6, max_lines=config.max_output_lines, max_chars=config.max_output_size))
            if error:
                print("    [ Error ]")
                print(format_output(error, indent=6, max_lines=config.max_output_lines, max_chars=config.max_output_size))
            if ask_yes("    ? Allow sending output? [y/N]: "):
                return CommandResult(requirement=self, stdout=output, stderr=error, success=success)


# Base class for data returned for requirements
class RequirementResult(BaseModel):
    requirement: Union[FileRequirement|CommandRequirement]

    def to_openai(self):
        return self.model_dump()


class FileResult(RequirementResult):
    # is_directory: bool
    metadata: dict
    # For files
    content: Optional[str] = None
    content_encoding: Optional[Literal["text", "base64"]] = None
    # For directories
    directory_listing: Optional[List[str]] = None

    def to_openai(self):
        data = super().to_openai()
        requirement = data.pop("requirement")
        data["path"] = requirement["path"]
        return data


class CommandResult(RequirementResult):
    success: bool
    stdout: Optional[str] = None
    stderr: Optional[str] = None

    def to_openai(self):
        data = super().to_openai()
        requirement = data.pop("requirement")
        data["command"] = requirement["command"]
        return data
