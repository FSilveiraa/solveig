from __future__ import annotations

import json
import subprocess

from pydantic import BaseModel, field_validator
from pathlib import Path
from typing import Literal, Union, Optional, List

import utils.file
from utils.misc import ask_yes, format_output
from plugins.hooks import HOOKS



# Base class for things the LLM can request
class Requirement(BaseModel):
    comment: str

    @field_validator("comment", mode="before")
    @classmethod
    def strip_name(cls, comment):
        return comment.strip()

    def solve(self, config):
        for (before_hook, requirements) in HOOKS.before:
            if not requirements or type(self) in requirements:
                before_hook(config, self)

        result = self._actually_solve(config)

        for (after_hook, requirements) in HOOKS.after:
            if not requirements or type(self) in requirements:
                after_hook(config, self, result)

        return result

    def _actually_solve(self, config) -> RequirementResult:
        raise NotImplementedError()


class FileRequirement(Requirement):
    path: str

    # Idk if I'm keeping this or how it fits into the current explicit permissions
    # def is_possible(self, config: SolveigConfig) -> bool:
    #     possible = False
    #     for path in config.allowed_paths:
    #         if Path(self.path).is_relative_to(path):
    #             if path.mode == "n":
    #                 return False
    #             elif self.mode_allowed(path.mode):
    #                 possible = True
    #     return possible
    #
    # @staticmethod
    # def mode_allowed(mode: str) -> bool:
    #     raise NotImplementedError()


class ReadRequirement(FileRequirement):
    only_read_metadata: bool

    def _actually_solve(self, config) -> ReadResult:
        abs_path = Path(self.path).expanduser().resolve()
        is_dir = abs_path.is_dir()

        print("  [ Read ]")
        print(f"    comment: \"{self.comment}\"")
        print(f"    path: {self.path} ({"directory" if is_dir else "file"})")

        if not abs_path.exists():
            print("    Skipping - This path does not exist.")
            return ReadResult(requirement=self, accepted=False, error="This path doesn't exist")

        metadata = content = encoding = entries = None
        accepted = True
        if is_dir:
            if ask_yes("    ? Allow reading directory listing and metadata? [y/N]: "):
                accepted = True
                metadata, entries = utils.file.read_metadata_and_entries(abs_path)
            return ReadResult(requirement=self, accepted=accepted, metadata=metadata, directory_listing=entries)
        else:
            # TODO: print the file size here so the user can have some idea of how much data they're sending and
            #  are about to print. If the LLM wants to read a 6GB .mkv file that should not be printed
            choice_read_file = input("    ? Allow reading file? [y=content+metadata / m=metadata / N=skip]: ").strip().lower()
            if choice_read_file in { "m", "y" }:
                # TODO: fix this messy flow, if the requirement is metadata-only then we shouldn't prompt user for contents,
                # plus `accepted` has a value assigned 3 times
                accepted = True
                print("    [ Metadata ]")
                metadata, _ = utils.file.read_metadata_and_entries(abs_path)
                print(format_output(json.dumps(metadata), indent=6, max_lines=config.max_output_lines, max_chars=config.max_output_size))
                if choice_read_file == "y":
                    content, encoding = utils.file.read_file(abs_path)
                    print("    [ Content ]")
                    print("      (Base64)" if encoding == "base64" else format_output(content, indent=6, max_lines=config.max_output_lines, max_chars=config.max_output_size))
                if not ask_yes(f"    ? Allow sending {"file content and " if content else ""}metadata? [y/N]: "):
                    content = encoding = metadata = None
                    accepted = False
            return ReadResult(requirement=self, accepted=accepted, metadata=metadata, content=content, content_encoding=encoding)


class WriteRequirement(FileRequirement):
    is_directory: bool
    content: Optional[str] = None

    def _actually_solve(self, config) -> WriteResult:
        abs_path = Path(self.path).expanduser().resolve()

        print("  [ Write ]")
        print(f"    comment: \"{self.comment}\"")
        # TODO also list real path if it's different from the LLM's path (and also for ReadRequirement)
        print(f"    path: {self.path} ({"directory" if self.is_directory else "file"})")
        if self.content:
            print("      [ Content ]")
            formatted_content = format_output(self.content, indent=8, max_lines=config.max_output_lines, max_chars=config.max_output_size)
            # TODO: make this print optional, or in a `less`-like window, or it will get messy
            print(formatted_content)

        if abs_path.exists():
            print(f"    ! Warning: this path already exists !")
            # don't re-write directories
            if self.is_directory:
                return WriteResult(requirement=self, accepted=False, error="This directory already exists")

        accepted = False
        if self.is_directory:
            if ask_yes("    ? Allow writing directory? [y/N]: "):
                accepted = True
                abs_path.mkdir(parents=True, exist_ok=False)
            return WriteResult(requirement=self, accepted=accepted)
        else:
            if not abs_path.parent.exists():
                print(f"    ! Warning: the parent directory '{abs_path.parent}' for this file does not exist")
                if not ask_yes(f"    ? Allow writing directory? [y/N]: "):
                    return WriteResult(requirement=self, accepted=False)
                abs_path.parent.mkdir(parents=True, exist_ok=False)

            if ask_yes(f"    ? Allow writing file{" and contents" if self.content else ""}? [y/N]: "):
                accepted=True
                abs_path.write_text(self.content if self.content else "", encoding="utf-8")
            return WriteResult(requirement=self, accepted=accepted)


class CommandRequirement(Requirement):
    command: str

    def _actually_solve(self, config) -> CommandResult:
        print(f"  [ Command ]")
        print(f"    comment: \"{self.comment}\"")
        print(f"    command: {self.command}")
        #print(f"    (type={self.type}, command='{self.command}')")
        if ask_yes("    ? Allow running command? [y/N]: "):
            # TODO review the whole 'accepted' thing. If I run a command, but don't send the output,
            #  that's confusing and should be differentiated from not running the command at all.
            #  or if anything at all is refused, maybe just say that in the error
            try:
                result = subprocess.run(self.command, shell=True, capture_output=True, text=True, timeout=10)
                output = result.stdout.strip()
                error = result.stderr.strip() if result.stderr else ""
            except Exception as e:
                error = str(e)
                print(error)
                return CommandResult(requirement=self, accepted=True, success=False, error=error)

            if output:
                print("    [ Output ]")
                print(format_output(output, indent=6, max_lines=config.max_output_lines, max_chars=config.max_output_size))
            else:
                print("    [ No Output ]")
            if error:
                print("    [ Error ]")
                print(format_output(error, indent=6, max_lines=config.max_output_lines, max_chars=config.max_output_size))
            if not ask_yes("    ? Allow sending output? [y/N]: "):
                output = error = None
            return CommandResult(requirement=self, accepted=True, success=True, stdout=output, error=error)
        return CommandResult(requirement=self, accepted=False)


# Base class for data returned for requirements
class RequirementResult(BaseModel):
    # we store the initial requirement for debugging/error printing,
    # then when JSON'ing we usually keep a couple of its fields in the result's body
    requirement: Optional[Union[ReadRequirement | WriteRequirement | CommandRequirement]] = None
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
