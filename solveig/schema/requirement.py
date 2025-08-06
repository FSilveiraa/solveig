from __future__ import annotations

import json
import subprocess

from pydantic import BaseModel, field_validator
from pathlib import Path
from typing import Literal, Union, Optional, List, TYPE_CHECKING

from .. import utils, SolveigConfig
from .. import plugins

if TYPE_CHECKING:
    from .result import RequirementResult, ReadResult, WriteResult, CommandResult
else:
    # Runtime imports - needed for instantiation
    from .result import ReadResult, WriteResult, CommandResult



# Base class for things the LLM can request
class Requirement(BaseModel):
    comment: str

    @field_validator("comment", mode="before")
    @classmethod
    def strip_name(cls, comment):
        return comment.strip()

    def _print(self, config):
        raise NotImplementedError()

    def solve(self, config):
        self._print(config)

        for (before_hook, requirements) in plugins.hooks.HOOKS.before:
            if not requirements or type(self) in requirements:
                before_result = before_hook(config, self)
                if before_result:
                    return before_result

        result = self._actually_solve(config)

        for (after_hook, requirements) in plugins.hooks.HOOKS.after:
            if not requirements or type(self) in requirements:
                after_result = after_hook(config, self, result)
                if after_result:
                    return after_result

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

    def _print(self, config):
        abs_path = Path(self.path).expanduser().resolve()
        is_dir = abs_path.is_dir()
        print("  [ Read ]")
        print(f"    comment: \"{self.comment}\"")
        print(f"    path: {self.path} ({"directory" if is_dir else "file"})")

    def _actually_solve(self, config) -> "ReadResult":
        abs_path = Path(self.path).expanduser().resolve()
        is_dir = abs_path.is_dir()
        
        # Pre-flight validation 
        try:
            utils.file.validate_read_access(self.path)
        except (FileNotFoundError, PermissionError) as e:
            print(f"    Skipping - {e}")
            return ReadResult(requirement=self, accepted=False, error=str(e))
        
        # Handle user interaction for different read types
        if is_dir:
            if utils.misc.ask_yes("    ? Allow reading directory listing and metadata? [y/N]: "):
                try:
                    file_data = utils.file.read_file_with_metadata(self.path, include_content=False)
                    return ReadResult(requirement=self, accepted=True, 
                                    metadata=file_data['metadata'], 
                                    directory_listing=file_data['directory_listing'])
                except (PermissionError, OSError) as e:
                    return ReadResult(requirement=self, accepted=False, error=str(e))
            else:
                return ReadResult(requirement=self, accepted=False)
        else:
            # File reading with user choices
            # TODO: print the file size here so the user can have some idea of how much data they're sending
            choice_read_file = input("    ? Allow reading file? [y=content+metadata / m=metadata / N=skip]: ").strip().lower()
            
            if choice_read_file not in {"m", "y"}:
                return ReadResult(requirement=self, accepted=False)
                
            # Read metadata first
            try:
                file_data = utils.file.read_file_with_metadata(self.path, include_content=False)
            except (PermissionError, OSError) as e:
                return ReadResult(requirement=self, accepted=False, error=str(e))
                
            print("    [ Metadata ]")
            print(utils.misc.format_output(json.dumps(file_data['metadata']), indent=6,
                                         max_lines=config.max_output_lines, max_chars=config.max_output_size))
            
            content = encoding = None
            if choice_read_file == "y":
                # Read content
                try:
                    file_data = utils.file.read_file_with_metadata(self.path, include_content=True)
                    content = file_data['content']
                    encoding = file_data['encoding']
                except (PermissionError, OSError, UnicodeDecodeError) as e:
                    return ReadResult(requirement=self, accepted=False, error=str(e))
                    
                print("    [ Content ]")
                print("      (Base64)" if encoding == "base64" else 
                      utils.misc.format_output(content, indent=6, max_lines=config.max_output_lines, 
                                             max_chars=config.max_output_size))
            
            # Final consent check
            if utils.misc.ask_yes(f"    ? Allow sending {'file content and ' if content else ''}metadata? [y/N]: "):
                return ReadResult(requirement=self, accepted=True, metadata=file_data['metadata'], 
                                content=content, content_encoding=encoding)
            else:
                return ReadResult(requirement=self, accepted=False)


class WriteRequirement(FileRequirement):
    is_directory: bool
    content: Optional[str] = None

    def _print(self, config):
        abs_path = Path(self.path).expanduser().resolve()

        print("  [ Write ]")
        print(f"    comment: \"{self.comment}\"")
        # TODO also list real path if it's different from the LLM's path (and also for ReadRequirement)
        print(f"    path: {self.path} ({"directory" if self.is_directory else "file"})")
        print(f"    real path: {abs_path}")
        if self.content:
            print("      [ Content ]")
            formatted_content = utils.misc.format_output(self.content, indent=8, max_lines=config.max_output_lines, max_chars=config.max_output_size)
            # TODO: make this print optional, or in a `less`-like window, or it will get messy
            print(formatted_content)

    def _actually_solve(self, config: SolveigConfig) -> "WriteResult":
        abs_path = Path(self.path).expanduser().resolve()

        # Show warning if path exists
        if abs_path.exists():
            print(f"    ! Warning: this path already exists !")

        # Get user consent before attempting operation
        operation_type = "directory" if self.is_directory else "file"
        content_desc = " and contents" if not self.is_directory and self.content else ""
        
        if utils.misc.ask_yes(f"    ? Allow writing {operation_type}{content_desc}? [y/N]: "):
            try:
                # Validate write access first
                utils.file.validate_write_access(
                    file_path=self.path,
                    is_directory=self.is_directory,
                    content=self.content,
                    min_disk_size_left=config.min_disk_space_left
                )
                
                # Perform the write operation
                content = self.content if self.content else ""
                utils.file.write_file_or_directory(self.path, self.is_directory, content)
                
                return WriteResult(requirement=self, accepted=True)
                
            except FileExistsError as e:
                return WriteResult(requirement=self, accepted=False, error=str(e))
            except PermissionError as e:
                return WriteResult(requirement=self, accepted=False, error=str(e))
            except OSError as e:
                return WriteResult(requirement=self, accepted=False, error=str(e))
            except UnicodeEncodeError as e:
                return WriteResult(requirement=self, accepted=False, error=f"Encoding error: {e}")
        else:
            return WriteResult(requirement=self, accepted=False)


class CommandRequirement(Requirement):
    command: str

    def _print(self, config):
        print(f"  [ Command ]")
        print(f"    comment: \"{self.comment}\"")
        print(f"    command: {self.command}")

    def _actually_solve(self, config) -> "CommandResult":
        if utils.misc.ask_yes("    ? Allow running command? [y/N]: "):
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
                print(utils.misc.format_output(output, indent=6, max_lines=config.max_output_lines, max_chars=config.max_output_size))
            else:
                print("    [ No Output ]")
            if error:
                print("    [ Error ]")
                print(utils.misc.format_output(error, indent=6, max_lines=config.max_output_lines, max_chars=config.max_output_size))
            if not utils.misc.ask_yes("    ? Allow sending output? [y/N]: "):
                output = error = None
            return CommandResult(requirement=self, accepted=True, success=True, stdout=output, error=error)
        return CommandResult(requirement=self, accepted=False)


