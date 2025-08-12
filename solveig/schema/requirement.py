from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, field_validator

from solveig.config import SolveigConfig
from solveig.plugins.hooks import HOOKS
from solveig.plugins.exceptions import PluginException, ProcessingError, ValidationError
# from .. import utils
from solveig.utils.filesystem import Filesystem

if TYPE_CHECKING:
    from solveig.interface import SolveigInterface

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

    @staticmethod
    def _get_path_info_str(
        path, abs_path, is_dir, destination_path=None, absolute_destination_path=None
    ):
        # if the real path is different from the canonical one (~/Documents vs /home/jdoe/Documents),
        # add it to the printed info
        path_print_str = f"{'🗁' if is_dir else '🗎'}  {path}"
        if str(abs_path) != path:
            path_print_str += f"  ({abs_path})"

        # if this is a two-path operation (copy, move), print the other path too
        if destination_path:
            path_print_str += f"  →  {destination_path}"
            if (
                absolute_destination_path
                and str(absolute_destination_path) != destination_path
            ):
                path_print_str += f" ({absolute_destination_path})"

        return path_print_str

    def solve(self, config: SolveigConfig, interface: SolveigInterface):
        with interface.with_group(self.title.title()):
            self.display_header(interface)

            # Run before hooks - they validate and can throw exceptions
            for before_hook, requirements in HOOKS.before:
                if not requirements or any(
                    isinstance(self, requirement_type)
                    for requirement_type in requirements
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
            try:
                result = self._actually_solve(config, interface)
            except Exception as error:
                # with interface.with_indent():
                interface.display_error(error)
                error_info = "Execution error"
                if interface.ask_yes_no(
                    "Send error message back to assistant? [y/N]: "
                ):
                    error_info = f": {str(error)}"
                result = self.create_error_result(error_info, accepted=False)

            # Run after hooks - they can process/modify result or throw exceptions
            for after_hook, requirements in HOOKS.after:
                if not requirements or any(
                    isinstance(self, requirement_type)
                    for requirement_type in requirements
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

    def display_header(self, interface: SolveigInterface) -> None:
        """Display the requirement header/summary using the interface directly."""
        interface.display_comment(self.comment)

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
        except ValueError as e:
            raise ValueError("Empty path") from e
        return path

    def display_header(self, interface: SolveigInterface) -> None:
        """Display read requirement header."""
        interface.display_comment(self.comment)
        abs_path = Filesystem.get_absolute_path(self.path)
        path_info = self._get_path_info_str(
            path=self.path, abs_path=abs_path, is_dir=Filesystem._is_dir(abs_path)
        )
        interface.show(path_info)

    def create_error_result(self, error_message: str, accepted: bool) -> ReadResult:
        """Create ReadResult with error."""
        return ReadResult(
            requirement=self,
            path=Filesystem.get_absolute_path(self.path),
            accepted=accepted,
            error=error_message,
        )

    def _actually_solve(
        self, config: SolveigConfig, interface: SolveigInterface
    ) -> ReadResult:
        abs_path = Filesystem.get_absolute_path(self.path)

        # Pre-flight validation
        try:
            Filesystem.validate_read_access(abs_path)
            # utils.file.validate_read_access(abs_path)
        except (FileNotFoundError, PermissionError, IsADirectoryError) as e:
            interface.display_error(f"Cannot access {abs_path}: {e}")
            return ReadResult(
                requirement=self, path=abs_path, accepted=False, error=str(e)
            )

        metadata = Filesystem.read_metadata(abs_path)
        try:
            listing = Filesystem.get_dir_listing(abs_path)
        except NotADirectoryError:
            listing = None
        interface.display_tree(metadata, listing)
        content = None

        if (
            not metadata.is_directory
            and not self.only_read_metadata
            and interface.ask_yes_no("Allow reading file contents? [y/N]: ")
        ):
            try:
                content, encoding = Filesystem.read_file(abs_path)
                metadata.encoding = encoding
            except (PermissionError, OSError, UnicodeDecodeError) as e:
                interface.display_error(f"Failed to read file contents: {e}")
                return ReadResult(
                    requirement=self, path=abs_path, accepted=False, error=str(e)
                )

            content_output = (
                "(Base64)" if encoding.lower() == "base64" else content
            )
            interface.display_text_block(content_output, title="Content")

        if interface.ask_yes_no(
            f"Allow sending {'file content and ' if content else ''}metadata? [y/N]: "
        ):
            return ReadResult(
                requirement=self,
                path=abs_path,
                accepted=True,
                metadata=metadata,
                content=content,
                directory_listing=listing,
            )
        else:
            return ReadResult(requirement=self, path=abs_path, accepted=False)


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
        except ValueError as e:
            raise ValueError("Empty path") from e
        return path

    def display_header(self, interface: SolveigInterface) -> None:
        """Display write requirement header."""
        interface.display_comment(self.comment)
        abs_path = Filesystem.get_absolute_path(self.path)
        path_info = self._get_path_info_str(
            path=self.path, abs_path=abs_path, is_dir=self.is_directory
        )
        interface.show(path_info)
        if self.content:
            interface.display_text_block(self.content, title="Content")

    def create_error_result(self, error_message: str, accepted: bool) -> WriteResult:
        """Create WriteResult with error."""
        return WriteResult(
            requirement=self,
            path=Filesystem.get_absolute_path(self.path),
            accepted=accepted,
            error=error_message,
        )

    def _actually_solve(
        self, config: SolveigConfig, interface: SolveigInterface
    ) -> WriteResult:
        abs_path = Filesystem.get_absolute_path(self.path)

        # Confirm if path exists
        try:
            Filesystem.validate_write_access(
                path=Filesystem.get_absolute_path(self.path),
                content=self.content,
                min_disk_size_left=config.min_disk_space_left,
            )

            metadata = Filesystem.read_metadata(abs_path)
            already_exists = True

            if already_exists:
                # If it got this far, it's a file
                interface.display_warning("This file already exists")
                interface.display_tree(metadata, None)
        except FileNotFoundError:
            # File does not exist
            already_exists = False

        question = (
            f"Allow {'creating' if self.is_directory and not already_exists else 'updating'} "
            f"{'directory' if self.is_directory else 'file'}"
            f"{' and contents' if not self.is_directory else ''}? [y/N]: "
        )
        if interface.ask_yes_no(question):
            try:
                # Perform the write operation
                if self.is_directory:
                    Filesystem.create_directory(abs_path)
                else:
                    Filesystem.write_file(abs_path, content=self.content)
                with interface.with_indent():
                    interface.display_success(f"{'Updated' if already_exists else 'Created'}")

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
            if not command:  # raises in case it's None or ""
                raise ValueError("Empty command")
        except ValueError as e:
            raise ValueError("Empty command") from e
        return command

    def display_header(self, interface: SolveigInterface) -> None:
        """Display command requirement header."""
        interface.display_comment(self.comment)
        interface.show(f"🗲  {self.command}")

    def create_error_result(self, error_message: str, accepted: bool) -> CommandResult:
        """Create CommandResult with error."""
        return CommandResult(
            requirement=self,
            command=self.command,
            accepted=accepted,
            success=False,
            error=error_message,
        )

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

    def _actually_solve(
        self, config: SolveigConfig, interface: SolveigInterface
    ) -> CommandResult:
        if interface.ask_yes_no("Allow running command? [y/N]: "):
            # TODO review the whole 'accepted' thing. If I run a command, but don't send the output,
            #  that's confusing and should be differentiated from not running the command at all.
            #  or if anything at all is refused, maybe just say that in the error
            try:
                output: str | None
                error: str | None
                output, error = self._execute_command(config)
            except Exception as e:
                error_str = str(e)
                interface.display_error(
                    f"Found error when running command: {error_str}"
                )
                return CommandResult(
                    requirement=self,
                    command=self.command,
                    accepted=True,
                    success=False,
                    error=error_str,
                )

            if output:
                interface.display_text_block(output, title="Output")
            else:
                interface.with_group("No output")
            if error:
                with interface.with_group("Error"):
                    interface.display_text_block(error, title="Error")
            if not interface.ask_yes_no("Allow sending output? [y/N]: "):
                output = ""
                error = ""
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
        except ValueError as e:
            raise ValueError("Empty path") from e
        return path

    def display_header(self, interface: SolveigInterface) -> None:
        """Display move requirement header."""
        interface.display_comment(self.comment)
        source_abs = Filesystem.get_absolute_path(self.source_path)
        dest_abs = Filesystem.get_absolute_path(self.destination_path)
        path_info = self._get_path_info_str(
            path=self.source_path,
            abs_path=source_abs,
            is_dir=Filesystem._is_dir(source_abs),
            destination_path=self.destination_path,
            absolute_destination_path=dest_abs,
        )
        interface.show(path_info)

    def create_error_result(self, error_message: str, accepted: bool) -> MoveResult:
        """Create MoveResult with error."""
        return MoveResult(
            requirement=self,
            accepted=accepted,
            error=error_message,
            source_path=Filesystem.get_absolute_path(self.source_path),
            destination_path=Filesystem.get_absolute_path(self.destination_path),
        )

    def _actually_solve(
        self, config: SolveigConfig, interface: SolveigInterface
    ) -> MoveResult:
        # Pre-flight validation
        abs_source_path = Filesystem.get_absolute_path(self.source_path)
        abs_destination_path = Filesystem.get_absolute_path(self.destination_path)
        error: Exception | None = None

        try:
            Filesystem.validate_read_access(abs_source_path)
            Filesystem.validate_write_access(abs_destination_path)
        except FileExistsError as e:
            # Destination path already exists
            error = e
            interface.display_warning("Destination path already exists")
            destination_metadata = Filesystem.read_metadata(abs_destination_path)
            try:
                destination_listing = Filesystem.get_dir_listing(abs_destination_path)
            except NotADirectoryError:
                destination_listing = None

            interface.display_tree(
                metadata=destination_metadata,
                listing=destination_listing,
                title="Destination Metadata",
            )

        except Exception as e:
            interface.display_error(f"Skipping: {e}")
            return MoveResult(
                requirement=self,
                accepted=False,
                error=str(e),
                source_path=abs_source_path,
                destination_path=abs_destination_path,
            )

        source_metadata = Filesystem.read_metadata(abs_source_path)
        try:
            source_listing = Filesystem.get_dir_listing(abs_source_path)
        except NotADirectoryError:
            source_listing = None
        interface.display_tree(
            metadata=source_metadata, listing=source_listing, title="Source Metadata"
        )

        # Get user consent
        if interface.ask_yes_no(
            f"Allow moving {abs_source_path} to {abs_destination_path}? [y/N]: "
        ):
            try:
                # Perform the move operation
                Filesystem.move(abs_source_path, abs_destination_path)

                with interface.with_indent():
                    interface.display_success("Moved")
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
                error=str(error) if error else None,
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
        except ValueError as e:
            raise ValueError("Empty path") from e
        return path

    def display_header(self, interface: SolveigInterface) -> None:
        """Display copy requirement header."""
        interface.display_comment(self.comment)
        source_abs = Filesystem.get_absolute_path(self.source_path)
        dest_abs = Filesystem.get_absolute_path(self.destination_path)
        path_info = self._get_path_info_str(
            path=self.source_path,
            abs_path=str(source_abs),
            is_dir=Filesystem._is_dir(source_abs),
            destination_path=dest_abs,
            absolute_destination_path=dest_abs,
        )
        interface.show(path_info)

    def create_error_result(self, error_message: str, accepted: bool) -> CopyResult:
        """Create CopyResult with error."""
        return CopyResult(
            requirement=self,
            accepted=accepted,
            error=error_message,
            source_path=Filesystem.get_absolute_path(self.source_path),
            destination_path=Filesystem.get_absolute_path(self.destination_path),
        )

    def _actually_solve(
        self, config: SolveigConfig, interface: SolveigInterface
    ) -> CopyResult:
        # Pre-flight validation
        abs_source_path = Filesystem.get_absolute_path(self.source_path)
        abs_destination_path = Filesystem.get_absolute_path(self.destination_path)
        error: Exception | None = None

        try:
            Filesystem.validate_read_access(abs_source_path)
            Filesystem.validate_write_access(abs_destination_path)
        except FileExistsError as e:
            # Destination file already exists - print information, allow user to overwrite
            error = e
            interface.display_warning("Destination path already exists")

            destination_metadata = Filesystem.read_metadata(abs_destination_path)
            try:
                destination_listing = Filesystem.get_dir_listing(abs_destination_path)
            except NotADirectoryError:
                destination_listing = None
            interface.display_tree(
                metadata=destination_metadata,
                listing=destination_listing,
                title="Destination Metadata",
            )

        except Exception as e:
            interface.display_error(f"Skipping: {e}")
            return CopyResult(
                requirement=self,
                accepted=False,
                error=str(e),
                source_path=abs_source_path,
                destination_path=abs_destination_path,
            )

        source_metadata = Filesystem.read_metadata(abs_source_path)
        try:
            source_listing = Filesystem.get_dir_listing(abs_source_path)
        except NotADirectoryError:
            source_listing = None

        interface.display_tree(
            metadata=source_metadata, listing=source_listing, title="Source Metadata"
        )

        # Get user consent
        if interface.ask_yes_no(
            f"Allow copying '{abs_source_path}' to '{abs_destination_path}'? [y/N]: "
        ):
            try:
                # Perform the copy operation
                Filesystem.copy(abs_source_path, abs_destination_path, min_space_left=config.min_disk_space_left)
                with interface.with_indent():
                    interface.display_success("Copied")
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
                error=str(
                    error
                ),  # allows us to return a "No" with the reason being that the file existed
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
        except ValueError as e:
            raise ValueError("Empty path") from e
        return path

    def display_header(self, interface: SolveigInterface) -> None:
        """Display delete requirement header."""
        interface.display_comment(self.comment)
        abs_path = Filesystem.get_absolute_path(self.path)
        path_info = self._get_path_info_str(
            path=self.path, abs_path=str(abs_path), is_dir=Filesystem._is_dir(abs_path)
        )
        interface.show(path_info)
        interface.display_warning("This operation is permanent and cannot be undone!")

    def create_error_result(self, error_message: str, accepted: bool) -> DeleteResult:
        """Create DeleteResult with error."""
        return DeleteResult(
            requirement=self,
            path=Filesystem.get_absolute_path(self.path),
            accepted=accepted,
            error=error_message,
        )

    def _actually_solve(
        self, config: SolveigConfig, interface: SolveigInterface
    ) -> DeleteResult:
        # Pre-flight validation
        abs_path = Filesystem.get_absolute_path(self.path)

        try:
            Filesystem.validate_delete_access(abs_path)
        except (FileNotFoundError, PermissionError) as e:
            interface.display_error(f"Skipping: {e}")
            return DeleteResult(
                requirement=self, accepted=False, error=str(e), path=abs_path
            )

        metadata = Filesystem.read_metadata(abs_path)
        try:
            listing = Filesystem.get_dir_listing(abs_path)
        except NotADirectoryError:
            listing = None
        interface.display_tree(metadata=metadata, listing=listing)

        # Get user consent (with extra warning)
        if interface.ask_yes_no(f"Permanently delete {abs_path}? [y/N]: "):
            try:
                # Perform the delete operation
                Filesystem.delete(abs_path)
                with interface.with_indent():
                    interface.display_success("Deleted")
                return DeleteResult(requirement=self, path=abs_path, accepted=True)
            except (PermissionError, OSError) as e:
                interface.display_error(f"Found error when deleting: {e}")
                return DeleteResult(
                    requirement=self, accepted=False, error=str(e), path=abs_path
                )
        else:
            return DeleteResult(requirement=self, accepted=False, path=abs_path)
