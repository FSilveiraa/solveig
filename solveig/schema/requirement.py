from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, field_validator

from .. import SolveigConfig, plugins, utils
from ..plugins.exceptions import PluginException, ProcessingError, ValidationError

if TYPE_CHECKING:
    from ..interface.base import RequirementPresentation, SolveigInterface
else:
    # Runtime import
    from ..interface.base import RequirementPresentation

if TYPE_CHECKING:
    from .result import (
        CommandResult,
        CopyResult,
        DeleteResult,
        MoveResult,
        ReadResult,
        RequirementResult,
        WriteResult,
    )
else:
    # Runtime imports - needed for instantiation
    from .result import (
        CommandResult,
        CopyResult,
        DeleteResult,
        MoveResult,
        ReadResult,
        WriteResult,
    )


# Base class for things the LLM can request
class Requirement(BaseModel, ABC):
    """
    Important: all statements that have side-effects (prints, network, filesystem operations)
    must be inside separate methods that can be mocked in a MockRequirement class for tests.
    Avoid all fields that are not strictly necessary, even if they are useful - like an `abs_path`
    computed from `path` for a ReadRequirement. These become part of the model and the LLM expects
    to fill them in.
    """

    title: str
    comment: str

    # @field_validator("comment", mode="before")
    # @classmethod
    # def strip_name(cls, comment):
    #     return comment.strip()

    @staticmethod
    def _get_path_info_str(
        path, abs_path, is_dir, destination_path=None, absolute_destination_path=None
    ):
        # if the real path is different from the canonical one (~/Documents vs /home/jdoe/Documents),
        # add it to the printed info
        path_print_str = f"{'🗁' if is_dir else '🗎'} {path}"
        if str(abs_path) != path:
            path_print_str += f" ({abs_path})"

        # if this is a two-path operation (copy, move), print the other path too
        if destination_path:
            path_print_str += f"  →  {destination_path}"
            if (
                absolute_destination_path
                and str(absolute_destination_path) != destination_path
            ):
                path_print_str += f" ({absolute_destination_path})"

        return path_print_str

    # def _print(self, config):
    #     """
    #     Example:
    #       [ Move ]
    #         ⸙ Move ~/run.sh to ~/run2.sh to rename the file
    #     """
    #     print(f"  [ {self.__class__.__name__.replace('Requirement', '').strip()} ]")
    #     print(f"    ❝ {self.comment}")

    def solve(self, config: SolveigConfig, interface: SolveigInterface):
        with interface.group(self.title.title()):

            presentation_data = self.get_presentation_data()
            interface.display_requirement(presentation_data)

            # Run before hooks - they validate and can throw exceptions
            for before_hook, requirements in plugins.hooks.HOOKS.before:
                if not requirements or any(
                    isinstance(self, requirement_type) for requirement_type in requirements
                ):
                    try:
                        before_hook(config, self)
                    except ValidationError as e:
                        # Plugin validation failed - return appropriate error result
                        return self.create_error_result(
                            f"Pre-processing failed: {e}", accepted=False
                        )
                    except PluginException as e:
                        # Other plugin error - return appropriate error result
                        return self.create_error_result(
                            f"Plugin error: {e}", accepted=False
                        )

            # Run the actual requirement solving
            result = self._actually_solve(config, interface)

            # Run after hooks - they can process/modify result or throw exceptions
            for after_hook, requirements in plugins.hooks.HOOKS.after:
                if not requirements or any(
                    isinstance(self, requirement_type) for requirement_type in requirements
                ):
                    try:
                        after_hook(config, self, result)
                    except ProcessingError as e:
                        # Plugin processing failed - return error result
                        return self.create_error_result(
                            f"Post-processing failed: {e}", accepted=result.accepted
                        )
                    except PluginException as e:
                        # Other plugin error - return error result
                        return self.create_error_result(
                            f"Plugin error: {e}", accepted=result.accepted
                        )

        return result

    ### Implement these:

    def get_presentation_data(self) -> RequirementPresentation:
        """Return structured presentation data for this requirement."""
        return RequirementPresentation(
            title=getattr(
                self,
                "title",
                self.__class__.__name__.replace("Requirement", "").strip(),
            ),
            comment=self.comment,
            details=[],
            warnings=None,
            content=None,
        )

    @abstractmethod
    def _actually_solve(self, config, interface: SolveigInterface) -> RequirementResult:
        """Solve yourself as a requirement following the config"""
        pass

    @abstractmethod
    def create_error_result(
        self, error_message: str, accepted: bool
    ) -> RequirementResult:
        """Create appropriate error result for this requirement type."""
        pass


class ReadRequirement(Requirement):
    title: Literal["read"] = "read"
    path: str
    only_read_metadata: bool

    @field_validator("path")
    @classmethod
    def path_not_empty(cls, path: str) -> str:
        try:
            path = path.strip()
            if not path:
                raise ValueError("Empty path")
        except ValueError:
            raise ValueError("Empty path")
        return path

    def get_presentation_data(self) -> RequirementPresentation:
        """Return structured presentation data for read requirement."""
        abs_path = utils.file.absolute_path(self.path)
        is_dir = abs_path.is_dir()
        path_info = self._get_path_info_str(
            path=self.path, abs_path=abs_path, is_dir=is_dir
        )

        return RequirementPresentation(
            title=self.title,
            comment=self.comment,
            details=[path_info],
            warnings=None,
            content=None,
        )

    # def _print(self, config):
    #     super()._print(config)
    #     abs_path = utils.file.absolute_path(self.path)
    #     is_dir = abs_path.is_dir()
    #     print(self.get_path_info_str(path=self.path, abs_path=abs_path, is_dir=is_dir))

    def create_error_result(self, error_message: str, accepted: bool) -> ReadResult:
        """Create ReadResult with error."""
        return ReadResult(
            requirement=self,
            path=utils.file.absolute_path(self.path),
            accepted=accepted,
            error=error_message,
        )

    def _validate_file_access(self, path: str | Path) -> None:
        """Validate r
        ead access to path (OS interaction - can be mocked)."""
        utils.file.validate_read_access(path)

    def _read_file_with_metadata(self, path: str | Path, include_content: bool = True) -> dict:
        """Read file with metadata (OS interaction - can be mocked)."""
        return utils.file.read_file_with_metadata(path, include_content=include_content)

    # def _ask_directory_consent(self, interface: SolveigInterface) -> bool:
    #     """Ask user consent for directory reading (user interaction - can be mocked)."""
    #     return interface.ask_directory_consent(
    #         "     "
    #     )

    # def _ask_file_read_choice(self) -> str:
    #     """Ask user what type of file read to perform (user interaction - can be mocked)."""
    #     return (
    #         input(
    #             "    ? Allow reading file? [y=content+metadata / m=metadata / N=skip]: "
    #         )
    #         .strip()
    #         .lower()
    #     )
    #
    # def _ask_final_consent(self, has_content: bool) -> bool:
    #     """Ask final consent to send data (user interaction - can be mocked)."""
    #     return utils.misc.ask_yes(
    #         f"    ? Allow sending {'file content and ' if has_content else ''}metadata? [y/N]: "
    #     )

    def _actually_solve(self, config: SolveigConfig, interface: SolveigInterface) -> ReadResult:
        abs_path = utils.file.absolute_path(self.path)
        is_dir = abs_path.is_dir()

        # Pre-flight validation
        try:
            self._validate_file_access(abs_path)
        except (FileNotFoundError, PermissionError) as e:
            interface.display_error(f"Cannot access {abs_path}: {e}")
            return ReadResult(
                requirement=self, path=abs_path, accepted=False, error=str(e)
            )

        # Handle user interaction for different read types
        if is_dir:
            if interface.ask_yes_no("Allow reading directory listing and metadata? [y/N]:"):
                try:
                    file_data = self._read_file_with_metadata(
                        self.path, include_content=False
                    )
                    return ReadResult(
                        requirement=self,
                        path=abs_path,
                        accepted=True,
                        metadata=file_data["metadata"],
                        directory_listing=file_data["directory_listing"],
                    )
                except (PermissionError, OSError) as e:
                    interface.display_error(f"Found error when reading {abs_path}: {e}")
                    return ReadResult(
                        requirement=self, path=abs_path, accepted=False, error=str(e)
                    )
            else:
                return ReadResult(requirement=self, path=abs_path, accepted=False)
        else:
            # File reading with user choices
            # TODO: print the file size here so the user can have some idea of how much data they're sending
            # choice_read_file = interface.ask_yes_no("? Allow reading file? [y=content+metadata / m=metadata / N=skip]: ") # self._ask_file_read_choice()
            if not interface.ask_yes_no(
                f"? Allow reading file {'metadata' if self.only_read_metadata else 'contents'}? [y/N]: "
            ):
                return ReadResult(requirement=self, path=abs_path, accepted=False)

            # Read metadata first
            try:
                file_data = self._read_file_with_metadata(abs_path, include_content=False)
            except (PermissionError, OSError) as e:
                interface.display_error(f"Error reading file metadata: {e}")
                return ReadResult(
                    requirement=self, path=abs_path, accepted=False, error=str(e)
                )
            with interface.group("Metadata"):
                interface.show(json.dumps(file_data["metadata"]))

            content = None
            encoding = None
            if not self.only_read_metadata:
                # Read content
                try:
                    file_data = self._read_file_with_metadata(
                        self.path, include_content=True
                    )
                    content = file_data["content"]
                    encoding = file_data["encoding"]
                except (PermissionError, OSError, UnicodeDecodeError) as e:
                    interface.display_error(f"Failed to read file contents: {e}")
                    return ReadResult(
                        requirement=self, path=abs_path, accepted=False, error=str(e)
                    )

                with interface.group("Content"):
                    content_output = ("(Base64)"
                        if encoding == "base64"
                        else utils.misc.format_output(
                            content,
                            indent=6,
                            max_lines=config.max_output_lines,
                            max_chars=config.max_output_size,
                        ))
                    interface.show(content_output)

            if interface.ask_yes_no(f"Allow sending {'file content and ' if content else ''}metadata? [y/N]: "):
                return ReadResult(
                    requirement=self,
                    path=abs_path,
                    accepted=True,
                    metadata=file_data["metadata"],
                    content=content,
                    content_encoding=encoding,
                )
            else:
                return ReadResult(requirement=self, path=abs_path, accepted=False)

            # print("    [ Metadata ]")
            # print(
            #     utils.misc.format_output(
            #         json.dumps(file_data["metadata"]),
            #         indent=6,
            #         max_lines=config.max_output_lines,
            #         max_chars=config.max_output_size,
            #     )
            # )
            #
            # content = encoding = None
            # if choice_read_file == "y":
            #     # Read content
            #     try:
            #         file_data = self._read_file_with_metadata(
            #             self.path, include_content=True
            #         )
            #         content = file_data["content"]
            #         encoding = file_data["encoding"]
            #     except (PermissionError, OSError, UnicodeDecodeError) as e:
            #         return ReadResult(
            #             requirement=self, path=abs_path, accepted=False, error=str(e)
            #         )
            #
            #     print("    [ Content ]")
            #     print(
            #         "      (Base64)"
            #         if encoding == "base64"
            #         else utils.misc.format_output(
            #             content,
            #             indent=6,
            #             max_lines=config.max_output_lines,
            #             max_chars=config.max_output_size,
            #         )
            #     )
            #
            # # Final consent check
            # if self._ask_final_consent(content is not None):
            #     return ReadResult(
            #         requirement=self,
            #         path=abs_path,
            #         accepted=True,
            #         metadata=file_data["metadata"],
            #         content=content,
            #         content_encoding=encoding,
            #     )
            # else:
            #     return ReadResult(requirement=self, path=abs_path, accepted=False)


class WriteRequirement(Requirement):
    title: Literal["write"] = "write"
    path: str
    is_directory: bool
    content: str | None = None

    @field_validator("path")
    @classmethod
    def path_not_empty(cls, path: str) -> str:
        try:
            path = path.strip()
            if not path:
                raise ValueError("Empty path")
        except ValueError:
            raise ValueError("Empty path")
        return path

    def get_presentation_data(self) -> RequirementPresentation:
        """Return structured presentation data for write requirement."""
        abs_path = utils.file.absolute_path(self.path)
        path_info = self._get_path_info_str(
            path=self.path, abs_path=abs_path, is_dir=self.is_directory
        )

        return RequirementPresentation(
            title=self.title,
            comment=self.comment,
            details=[path_info],
            warnings=None,
            content=self.content if self.content else None,
        )

    # def _print(self, config):
    #     super()._print(config)
    #     abs_path = utils.file.absolute_path(self.path)
    #     print(
    #         self.get_path_info_str(
    #             path=self.path, abs_path=abs_path, is_dir=self.is_directory
    #         )
    #     )
    #     if self.content:
    #         print("      [ Content ]")
    #         formatted_content = utils.misc.format_output(
    #             self.content,
    #             indent=8,
    #             max_lines=config.max_output_lines,
    #             max_chars=config.max_output_size,
    #         )
    #         # TODO: make this print optional, or in a `less`-like window, or it will get messy
    #         print(formatted_content)

    def create_error_result(self, error_message: str, accepted: bool) -> WriteResult:
        """Create WriteResult with error."""
        return WriteResult(
            requirement=self,
            path=utils.file.absolute_path(self.path),
            accepted=accepted,
            error=error_message,
        )

    def _path_exists(self, abs_path: Path) -> bool:
        """Check if path exists (OS interaction - can be mocked)."""
        return abs_path.exists()

    # def _ask_write_consent(self, interface: SolveigInterface, is_dir: bool, has_content: bool) -> bool:
    #     """Ask write consent."""
    #     question = f"Allow writing {'directory' if is_dir else 'file'}{' and contents' if not is_dir else ''}? [y/N]: "
    #     return interface.ask_yes_no(question)

    # def _ask_write_consent(self, operation_type: str, content_desc: str) -> bool:
    #     """Ask user consent for write operation (user interaction - can be mocked)."""
    #     return utils.misc.ask_yes(
    #         f"Allow writing {operation_type}{content_desc}? [y/N]: "
    #     )

    def _validate_write_access(self, config: SolveigConfig) -> None:
        """Validate write access (OS interaction - can be mocked)."""
        utils.file.validate_write_access(
            file_path=utils.file.absolute_path(self.path),
            is_directory=self.is_directory,
            content=self.content,
            min_disk_size_left=config.min_disk_space_left,
        )

    def _write_file_or_directory(self, path: str | Path, content: str | None = None) -> None:
        """Write file or directory (OS interaction - can be mocked)."""
        content = content or self.content or "" # cannot be None
        utils.file.write_file_or_directory(path, self.is_directory, content)

    def _actually_solve(self, config: SolveigConfig, interface: SolveigInterface) -> WriteResult:
        abs_path = utils.file.absolute_path(self.path)
        is_directory = abs_path.is_dir()

        # Show warning if path exists
        already_exists = self._path_exists(abs_path)
        if already_exists:
            if is_directory:
                raise ValueError("Cannot overwrite directory")
            else:
                interface.display_warning("This path already exist")

        # Get user consent before attempting operation
        # operation_type = "directory" if self.is_directory else "file"
        # content_desc = " and contents" if not self.is_directory and self.content else ""

        # if self._ask_write_consent(operation_type, content_desc):
        question = (
            f"Allow {'creating' if is_directory and not already_exists else 'updating'} "
            f"{'directory' if is_directory else 'file'}"
            f"{' and contents' if not is_directory else ''}? [y/N]: "
        )
        if interface.ask_yes_no(question):
            try:
                # Validate write access first
                self._validate_write_access(config)

                # Perform the write operation
                self._write_file_or_directory(abs_path)
                interface.show(f"✓ {'Updated' if already_exists else 'Created'}", level=interface.current_level + 1)

                return WriteResult(requirement=self, path=abs_path, accepted=True)

            except Exception as e:
                interface.display_error(f"Found error when writing file: {e}")
                return WriteResult(
                    requirement=self,
                    path=abs_path,
                    accepted=False,
                    error=f"Encoding error: {e}",
                )

        else:
            return WriteResult(requirement=self, path=abs_path, accepted=False)


class CommandRequirement(Requirement):
    title: Literal["command"] = "command"
    command: str

    @field_validator("command")
    @classmethod
    def path_not_empty(cls, command: str) -> str:
        try:
            command = command.strip()
            if not command: # raises in case it's None or ""
                raise ValueError("Empty command")
        except ValueError:
            raise ValueError("Empty command")
        return command

    def get_presentation_data(self) -> RequirementPresentation:
        """Return structured presentation data for command requirement."""
        return RequirementPresentation(
            title=self.title,
            comment=self.comment,
            details=[f"🗲 {self.command}"],
            warnings=None,
            content=None,
        )

    # def _print(self, config):
    #     super()._print(config)
    #     print(f"    🗲 {self.command}")

    def create_error_result(self, error_message: str, accepted: bool) -> CommandResult:
        """Create CommandResult with error."""
        return CommandResult(
            requirement=self,
            command=self.command,
            accepted=accepted,
            success=False,
            error=error_message,
        )

    # def _ask_run_consent(self, interface: SolveigInterface) -> bool:
    #     """Ask user consent for running command (user interaction - can be mocked)."""
    #     return interface.ask_yes_no("Allow running command? [y/N]: ")

    def _execute_command(self, config: SolveigConfig) -> tuple[str, str]:
        """Execute command and return stdout, stderr (OS interaction - can be mocked)."""
        if self.command:
            result = subprocess.run(
                self.command, shell=True, capture_output=True, text=True, timeout=10
            )
            output = result.stdout.strip() if result.stdout else ""
            error = result.stderr.strip() if result.stderr else ""
            return output, error
        raise ValueError("Empty command")

    # def _ask_output_consent(self) -> bool:
    #     """Ask user consent for sending output (user interaction - can be mocked)."""
    #     return utils.misc.ask_yes("    ? Allow sending output? [y/N]: ")

    def _actually_solve(self, config: SolveigConfig, interface: SolveigInterface) -> CommandResult:
        if interface.ask_yes_no("Allow running command? [y/N]: "):
            # TODO review the whole 'accepted' thing. If I run a command, but don't send the output,
            #  that's confusing and should be differentiated from not running the command at all.
            #  or if anything at all is refused, maybe just say that in the error
            try:
                output, error = self._execute_command(config)
            except Exception as e:
                error_str = str(e)
                interface.display_error(f"Found error when running command: {error_str}")
                # print(f"      {error_str}")
                return CommandResult(
                    requirement=self,
                    command=self.command,
                    accepted=True,
                    success=False,
                    error=error_str,
                )

            if output:
                with interface.group("Output"):
                    interface.show(utils.misc.format_output(
                        output,
                        indent=6,
                        max_lines=config.max_output_lines,
                        max_chars=config.max_output_size,
                    ))
                # print(
                #     utils.misc.format_output(
                #         output,
                #         indent=6,
                #         max_lines=config.max_output_lines,
                #         max_chars=config.max_output_size,
                #     )
                # )
            else:
                interface.group("No output")
                # print("    [ No Output ]")
            if error:
                with interface.group("Error"):
                    interface.show(utils.misc.format_output(
                        error, indent=6, max_lines=config.max_output_size, max_chars=config.max_output_size
                    ))
                # print(
                #     utils.misc.format_output(
                #         error,
                #         indent=6,
                #         max_lines=config.max_output_lines,
                #         max_chars=config.max_output_size,
                #     )
                # )
            if not interface.ask_yes_no("Allow sending output? [y/N]: "):
                output = None
                error = None
            return CommandResult(
                requirement=self,
                command=self.command,
                accepted=True,
                success=True,
                stdout=output,
                error=error,
            )
        return CommandResult(requirement=self, command=self.command, accepted=False)


class MoveRequirement(Requirement):
    title: Literal["move"] = "move"
    source_path: str
    destination_path: str

    @field_validator("source_path", "destination_path", mode="before")
    @classmethod
    def strip_and_check(cls, path: str) -> str:
        try:
            path = path.strip()
            if not path:
                raise ValueError("Empty path")
        except ValueError:
            raise ValueError("Empty path")
        return path

    def get_presentation_data(self) -> RequirementPresentation:
        """Return structured presentation data for move requirement."""
        source_abs = utils.file.absolute_path(self.source_path)
        dest_abs = utils.file.absolute_path(self.destination_path)
        path_info = self._get_path_info_str(
            path=self.source_path,
            abs_path=str(source_abs),
            is_dir=source_abs.is_dir(),
            destination_path=dest_abs,
            absolute_destination_path=dest_abs,
        )

        return RequirementPresentation(
            title=self.title,
            comment=self.comment,
            details=[path_info],
            warnings=None,
            content=None,
        )

    # def _print(self, config):
    #     super()._print(config)
    #     source_abs = utils.file.absolute_path(self.source_path)
    #     dest_abs = utils.file.absolute_path(self.destination_path)
    #     print(
    #         self.get_path_info_str(
    #             path=self.source_path,
    #             abs_path=str(source_abs),
    #             is_dir=source_abs.is_dir(),
    #             destination_path=dest_abs,
    #             absolute_destination_path=dest_abs,
    #         )
    #     )

    def create_error_result(self, error_message: str, accepted: bool) -> MoveResult:
        """Create MoveResult with error."""
        return MoveResult(
            requirement=self,
            accepted=accepted,
            error=error_message,
            source_path=utils.file.absolute_path(self.source_path),
            destination_path=utils.file.absolute_path(self.destination_path),
        )

    def _validate_move_access(self) -> None:
        """Validate move access (OS interaction - can be mocked)."""
        utils.file.validate_move_access(self.source_path, self.destination_path)

    # def _ask_move_consent(self) -> bool:
    #     """Ask user consent for move operation (user interaction - can be mocked)."""
    #     return utils.misc.ask_yes(
    #         f"    ? Allow moving '{self.source_path}' to '{self.destination_path}'? [y/N]: "
    #     )

    def _move_file_or_directory(self) -> None:
        """Move file or directory (OS interaction - can be mocked)."""
        utils.file.move_file_or_directory(self.source_path, self.destination_path)

    def _actually_solve(self, config: SolveigConfig, interface: SolveigInterface) -> MoveResult:
        # Pre-flight validation
        abs_source_path = utils.file.absolute_path(self.source_path)
        abs_destination_path = utils.file.absolute_path(self.destination_path)

        try:
            self._validate_move_access()
        except (FileNotFoundError, PermissionError, OSError) as e:
            interface.display_error(f"Skipping: {e}")
            # print(f"    ✖ Skipping - {e}")
            return MoveResult(
                requirement=self,
                accepted=False,
                error=str(e),
                source_path=abs_source_path,
                destination_path=abs_destination_path,
            )

        # Get user consent
        if interface.ask_yes_no(f"Allow moving {self.source_path} to {self.destination_path}? [y/N]: "):
            try:
                # Perform the move operation
                self._move_file_or_directory()
                interface.indent_base += 1

                interface.show("✓ Moved", level=interface.current_level+1)
                # print("      ✓ Moved")
                return MoveResult(
                    requirement=self,
                    accepted=True,
                    source_path=abs_source_path,
                    destination_path=abs_destination_path,
                )
            except (PermissionError, OSError, FileExistsError) as e:
                interface.display_error(f"Found error when moving: {e}")
                return MoveResult(
                    requirement=self,
                    accepted=False,
                    error=str(e),
                    source_path=abs_source_path,
                    destination_path=abs_destination_path,
                )
        else:
            return MoveResult(
                requirement=self,
                accepted=False,
                source_path=abs_source_path,
                destination_path=abs_destination_path,
            )


class CopyRequirement(Requirement):
    title: Literal["copy"] = "copy"
    source_path: str
    destination_path: str

    @field_validator("source_path", "destination_path", mode="before")
    @classmethod
    def strip_and_check(cls, path: str) -> str:
        try:
            path = path.strip()
            if not path:
                raise ValueError("Empty path")
        except ValueError:
            raise ValueError("Empty path")
        return path

    def get_presentation_data(self) -> RequirementPresentation:
        """Return structured presentation data for copy requirement."""
        source_abs = utils.file.absolute_path(self.source_path)
        dest_abs = utils.file.absolute_path(self.destination_path)
        path_info = self._get_path_info_str(
            path=self.source_path,
            abs_path=str(source_abs),
            is_dir=source_abs.is_dir(),
            destination_path=dest_abs,
            absolute_destination_path=dest_abs,
        )

        return RequirementPresentation(
            title=self.title,
            comment=self.comment,
            details=[path_info],
            warnings=None,
            content=None,
        )

    # def _print(self, config):
    #     super()._print(config)
    #     source_abs = utils.file.absolute_path(self.source_path)
    #     dest_abs = utils.file.absolute_path(self.destination_path)
    #     print(
    #         self.get_path_info_str(
    #             path=self.source_path,
    #             abs_path=str(source_abs),
    #             is_dir=source_abs.is_dir(),
    #             destination_path=dest_abs,
    #             absolute_destination_path=dest_abs,
    #         )
    #     )

    def create_error_result(self, error_message: str, accepted: bool) -> CopyResult:
        """Create CopyResult with error."""
        return CopyResult(
            requirement=self,
            accepted=accepted,
            error=error_message,
            source_path=utils.file.absolute_path(self.source_path),
            destination_path=utils.file.absolute_path(self.destination_path),
        )

    def _validate_copy_access(self) -> None:
        """Validate copy access (OS interaction - can be mocked)."""
        utils.file.validate_copy_access(self.source_path, self.destination_path)

    # def _ask_copy_consent(self) -> bool:
    #     """Ask user consent for copy operation (user interaction - can be mocked)."""
    #     return utils.misc.ask_yes(
    #         f"    ? Allow copying '{self.source_path}' to '{self.destination_path}'? [y/N]: "
    #     )

    def _copy_file_or_directory(self) -> None:
        """Copy file or directory (OS interaction - can be mocked)."""
        utils.file.copy_file_or_directory(self.source_path, self.destination_path)

    def _actually_solve(self, config: SolveigConfig, interface: SolveigInterface) -> CopyResult:
        # Pre-flight validation
        abs_source_path = utils.file.absolute_path(self.source_path)
        abs_destination_path = utils.file.absolute_path(self.destination_path)
        try:
            self._validate_copy_access()
        except (FileNotFoundError, PermissionError, OSError) as e:
            interface.display_error(f"Skipping: {e}")
            return CopyResult(
                requirement=self,
                accepted=False,
                error=str(e),
                source_path=abs_source_path,
                destination_path=abs_destination_path,
            )

        # Get user consent
        if interface.ask_yes_no(f"Allow copying '{self.source_path}' to '{self.destination_path}'? [y/N]: "):
        # if self._ask_copy_consent():
            try:
                # Perform the copy operation
                self._copy_file_or_directory()
                interface.show("✓ Copied", level=interface.current_level+1)
                return CopyResult(
                    requirement=self,
                    accepted=True,
                    source_path=abs_source_path,
                    destination_path=abs_destination_path,
                )
            except (PermissionError, OSError, FileExistsError) as e:
                interface.display_error(f"Found error when copying: {e}")
                return CopyResult(
                    requirement=self,
                    accepted=False,
                    error=str(e),
                    source_path=abs_source_path,
                    destination_path=abs_destination_path,
                )
        else:
            return CopyResult(
                requirement=self,
                accepted=False,
                source_path=abs_source_path,
                destination_path=abs_destination_path,
            )


class DeleteRequirement(Requirement):
    title: Literal["delete"] = "delete"
    path: str

    @field_validator("path", mode="before")
    @classmethod
    def strip_and_check(cls, path: str) -> str:
        try:
            path = path.strip()
            if not path:
                raise ValueError("Empty path")
        except ValueError:
            raise ValueError("Empty path")
        return path

    def get_presentation_data(self) -> RequirementPresentation:
        """Return structured presentation data for delete requirement."""
        abs_path = utils.file.absolute_path(self.path)
        is_dir = abs_path.is_dir() if abs_path.exists() else False
        path_info = self._get_path_info_str(
            path=self.path, abs_path=str(abs_path), is_dir=is_dir
        )

        return RequirementPresentation(
            title=self.title,
            comment=self.comment,
            details=[path_info],
            warnings=["This operation is permanent and cannot be undone!"],
            content=None,
        )

    # def _print(self, config):
    #     super()._print(config)
    #     abs_path = utils.file.absolute_path(self.path)
    #     is_dir = abs_path.is_dir() if abs_path.exists() else False
    #     print(
    #         self.get_path_info_str(
    #             path=self.path, abs_path=str(abs_path), is_dir=is_dir
    #         )
    #     )
    #     print("    ⚠︎ This operation is permanent and cannot be undone!")

    def create_error_result(self, error_message: str, accepted: bool) -> DeleteResult:
        """Create DeleteResult with error."""
        return DeleteResult(
            requirement=self,
            path=utils.file.absolute_path(self.path),
            accepted=accepted,
            error=error_message,
        )

    def _validate_delete_access(self) -> None:
        """Validate delete access (OS interaction - can be mocked)."""
        utils.file.validate_delete_access(self.path)

    # def _ask_delete_consent(self) -> bool:
    #     """Ask user consent for delete operation (user interaction - can be mocked)."""
    #     return utils.misc.ask_yes(f"    ? Permanently delete '{self.path}'? [y/N]: ")

    def _delete_file_or_directory(self) -> None:
        """Delete file or directory (OS interaction - can be mocked)."""
        utils.file.delete_file_or_directory(self.path)

    def _actually_solve(self, config: SolveigConfig, interface: SolveigInterface) -> DeleteResult:
        # Pre-flight validation
        abs_path = utils.file.absolute_path(self.path)

        try:
            self._validate_delete_access()
        except (FileNotFoundError, PermissionError) as e:
            interface.display_error(f"Skipping: {e}")
            return DeleteResult(
                requirement=self, accepted=False, error=str(e), path=abs_path
            )

        # Get user consent (with extra warning)
        if interface.ask_user(f"Permanently delete {abs_path}? [y/N]: "):
            try:
                # Perform the delete operation
                self._delete_file_or_directory()
                interface.show("✓ Deleted", level=interface.current_level + 1)
                return DeleteResult(requirement=self, path=abs_path, accepted=True)
            except (PermissionError, OSError) as e:
                interface.display_error(f"Found error when deleting: {e}")
                return DeleteResult(
                    requirement=self, accepted=False, error=str(e), path=abs_path
                )
        else:
            return DeleteResult(requirement=self, accepted=False, path=abs_path)
