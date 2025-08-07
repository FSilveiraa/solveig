from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, field_validator

from .. import SolveigConfig, plugins, utils
from ..plugins.exceptions import PluginException, ProcessingError, ValidationError

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
class Requirement(BaseModel):
    """
    Important: all statements that have side-effects (prints, network, filesystem operations)
    must be inside separate methods that can be mocked in a MockRequirement class for tests.
    Avoid all fields that are not strictly necessary, even if they are useful - like an `abs_path`
    computed from `path` for a ReadRequirement. These become part of the model and the LLM expects
    to fill them in.
    """

    comment: str

    @field_validator("comment", mode="before")
    @classmethod
    def strip_name(cls, comment):
        return comment.strip()

    def _print(self, config):
        raise NotImplementedError()

    def solve(self, config):
        self._print(config)

        # Run before hooks - they validate and can throw exceptions
        for before_hook, requirements in plugins.hooks.HOOKS.before:
            if not requirements or any(
                isinstance(self, requirement_type) for requirement_type in requirements
            ):
                try:
                    before_hook(config, self)
                except ValidationError as e:
                    # Plugin validation failed - return appropriate error result
                    return self._create_error_result(
                        f"Pre-processing failed: {e}", accepted=False
                    )
                except PluginException as e:
                    # Other plugin error - return appropriate error result
                    return self._create_error_result(
                        f"Plugin error: {e}", accepted=False
                    )

        # Run the actual requirement solving
        result = self._actually_solve(config)

        # Run after hooks - they can process/modify result or throw exceptions
        for after_hook, requirements in plugins.hooks.HOOKS.after:
            if not requirements or any(
                isinstance(self, requirement_type) for requirement_type in requirements
            ):
                try:
                    after_hook(config, self, result)
                except ProcessingError as e:
                    # Plugin processing failed - return error result
                    return self._create_error_result(
                        f"Post-processing failed: {e}", accepted=result.accepted
                    )
                except PluginException as e:
                    # Other plugin error - return error result
                    return self._create_error_result(
                        f"Plugin error: {e}", accepted=result.accepted
                    )

        return result

    def _actually_solve(self, config) -> RequirementResult:
        raise NotImplementedError()

    def _create_error_result(
        self, error_message: str, accepted: bool
    ) -> RequirementResult:
        """Create appropriate error result for this requirement type."""
        raise NotImplementedError()


class ReadRequirement(Requirement):
    path: str
    only_read_metadata: bool

    @field_validator("path")
    @classmethod
    def path_not_empty(cls, path):
        if not path.strip():
            raise ValueError("Empty path")
        return path

    def _print(self, config):
        abs_path = utils.file.absolute_path(self.path)
        is_dir = abs_path.is_dir()
        print("  [ Read ]")
        print(f'    comment: "{self.comment}"')
        print(f"    path: {self.path} ({'directory' if is_dir else 'file'})")

    def _create_error_result(self, error_message: str, accepted: bool) -> ReadResult:
        """Create ReadResult with error."""
        return ReadResult(
            requirement=self,
            path=utils.file.absolute_path(self.path),
            accepted=accepted,
            error=error_message,
        )

    def _validate_read_access(self, path: str | Path) -> None:
        """Validate read access to path (OS interaction - can be mocked)."""
        utils.file.validate_read_access(path)

    def _read_file_with_metadata(
        self, path: str | Path, include_content: bool = True
    ) -> dict:
        """Read file with metadata (OS interaction - can be mocked)."""
        return utils.file.read_file_with_metadata(path, include_content=include_content)

    def _ask_directory_consent(self) -> bool:
        """Ask user consent for directory reading (user interaction - can be mocked)."""
        return utils.misc.ask_yes(
            "    ? Allow reading directory listing and metadata? [y/N]: "
        )

    def _ask_file_read_choice(self) -> str:
        """Ask user what type of file read to perform (user interaction - can be mocked)."""
        return (
            input(
                "    ? Allow reading file? [y=content+metadata / m=metadata / N=skip]: "
            )
            .strip()
            .lower()
        )

    def _ask_final_consent(self, has_content: bool) -> bool:
        """Ask final consent to send data (user interaction - can be mocked)."""
        return utils.misc.ask_yes(
            f"    ? Allow sending {'file content and ' if has_content else ''}metadata? [y/N]: "
        )

    def _actually_solve(self, config) -> ReadResult:
        abs_path = utils.file.absolute_path(self.path)
        is_dir = abs_path.is_dir()

        # Pre-flight validation
        try:
            self._validate_read_access(abs_path)
        except (FileNotFoundError, PermissionError) as e:
            print(f"    Skipping - {e}")
            return ReadResult(
                requirement=self, path=abs_path, accepted=False, error=str(e)
            )

        # Handle user interaction for different read types
        if is_dir:
            if self._ask_directory_consent():
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
                    return ReadResult(
                        requirement=self, path=abs_path, accepted=False, error=str(e)
                    )
            else:
                return ReadResult(requirement=self, path=abs_path, accepted=False)
        else:
            # File reading with user choices
            # TODO: print the file size here so the user can have some idea of how much data they're sending
            choice_read_file = self._ask_file_read_choice()

            if choice_read_file not in {"m", "y"}:
                return ReadResult(requirement=self, path=abs_path, accepted=False)

            # Read metadata first
            try:
                file_data = self._read_file_with_metadata(
                    abs_path, include_content=False
                )
            except (PermissionError, OSError) as e:
                return ReadResult(
                    requirement=self, path=abs_path, accepted=False, error=str(e)
                )

            print("    [ Metadata ]")
            print(
                utils.misc.format_output(
                    json.dumps(file_data["metadata"]),
                    indent=6,
                    max_lines=config.max_output_lines,
                    max_chars=config.max_output_size,
                )
            )

            content = encoding = None
            if choice_read_file == "y":
                # Read content
                try:
                    file_data = self._read_file_with_metadata(
                        self.path, include_content=True
                    )
                    content = file_data["content"]
                    encoding = file_data["encoding"]
                except (PermissionError, OSError, UnicodeDecodeError) as e:
                    return ReadResult(
                        requirement=self, path=abs_path, accepted=False, error=str(e)
                    )

                print("    [ Content ]")
                print(
                    "      (Base64)"
                    if encoding == "base64"
                    else utils.misc.format_output(
                        content,
                        indent=6,
                        max_lines=config.max_output_lines,
                        max_chars=config.max_output_size,
                    )
                )

            # Final consent check
            if self._ask_final_consent(content is not None):
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


class WriteRequirement(Requirement):
    path: str
    is_directory: bool
    content: str | None = None

    def _print(self, config):
        abs_path = utils.file.absolute_path(self.path)

        print("  [ Write ]")
        print(f'    comment: "{self.comment}"')
        # TODO also list real path if it's different from the LLM's path (and also for ReadRequirement)
        print(f"    path: {self.path} ({'directory' if self.is_directory else 'file'})")
        print(f"    real path: {abs_path}")
        if self.content:
            print("      [ Content ]")
            formatted_content = utils.misc.format_output(
                self.content,
                indent=8,
                max_lines=config.max_output_lines,
                max_chars=config.max_output_size,
            )
            # TODO: make this print optional, or in a `less`-like window, or it will get messy
            print(formatted_content)

    def _create_error_result(self, error_message: str, accepted: bool) -> WriteResult:
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

    def _ask_write_consent(self, operation_type: str, content_desc: str) -> bool:
        """Ask user consent for write operation (user interaction - can be mocked)."""
        return utils.misc.ask_yes(
            f"    ? Allow writing {operation_type}{content_desc}? [y/N]: "
        )

    def _validate_write_access(self, config: SolveigConfig) -> None:
        """Validate write access (OS interaction - can be mocked)."""
        utils.file.validate_write_access(
            file_path=utils.file.absolute_path(self.path),
            is_directory=self.is_directory,
            content=self.content,
            min_disk_size_left=config.min_disk_space_left,
        )

    def _write_file_or_directory(
        self, path: str | Path, is_directory: bool, content: str
    ) -> None:
        """Write file or directory (OS interaction - can be mocked)."""
        utils.file.write_file_or_directory(path, is_directory, content)

    def _actually_solve(self, config: SolveigConfig) -> WriteResult:
        abs_path = utils.file.absolute_path(self.path)

        # Show warning if path exists
        if self._path_exists(abs_path):
            print("    ! Warning: this path already exists !")

        # Get user consent before attempting operation
        operation_type = "directory" if self.is_directory else "file"
        content_desc = " and contents" if not self.is_directory and self.content else ""

        if self._ask_write_consent(operation_type, content_desc):
            try:
                # Validate write access first
                self._validate_write_access(config)

                # Perform the write operation
                content = self.content if self.content else ""
                self._write_file_or_directory(abs_path, self.is_directory, content)

                return WriteResult(requirement=self, path=abs_path, accepted=True)

            except FileExistsError as e:
                return WriteResult(
                    requirement=self, path=abs_path, accepted=False, error=str(e)
                )
            except PermissionError as e:
                return WriteResult(
                    requirement=self, path=abs_path, accepted=False, error=str(e)
                )
            except OSError as e:
                return WriteResult(
                    requirement=self, path=abs_path, accepted=False, error=str(e)
                )
            except UnicodeEncodeError as e:
                return WriteResult(
                    requirement=self,
                    path=abs_path,
                    accepted=False,
                    error=f"Encoding error: {e}",
                )
        else:
            return WriteResult(requirement=self, path=abs_path, accepted=False)


class CommandRequirement(Requirement):
    command: str

    def _print(self, config):
        print("  [ Command ]")
        print(f'    comment: "{self.comment}"')
        print(f"    command: {self.command}")

    def _create_error_result(self, error_message: str, accepted: bool) -> CommandResult:
        """Create CommandResult with error."""
        return CommandResult(
            requirement=self,
            command=self.command,
            accepted=accepted,
            success=False,
            error=error_message,
        )

    def _ask_run_consent(self) -> bool:
        """Ask user consent for running command (user interaction - can be mocked)."""
        return utils.misc.ask_yes("    ? Allow running command? [y/N]: ")

    def _execute_command(self, command: str) -> tuple[str | None, str | None]:
        """Execute command and return stdout, stderr (OS interaction - can be mocked)."""
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=10
        )
        output = result.stdout.strip() if result.stdout else None
        error = result.stderr.strip() if result.stderr else None
        return output, error

    def _ask_output_consent(self) -> bool:
        """Ask user consent for sending output (user interaction - can be mocked)."""
        return utils.misc.ask_yes("    ? Allow sending output? [y/N]: ")

    def _actually_solve(self, config) -> CommandResult:
        if self._ask_run_consent():
            # TODO review the whole 'accepted' thing. If I run a command, but don't send the output,
            #  that's confusing and should be differentiated from not running the command at all.
            #  or if anything at all is refused, maybe just say that in the error
            try:
                output, error = self._execute_command(self.command)
            except Exception as e:
                error_str = str(e)
                print(error_str)
                return CommandResult(
                    requirement=self,
                    command=self.command,
                    accepted=True,
                    success=False,
                    error=error_str,
                )

            if output:
                print("    [ Output ]")
                print(
                    utils.misc.format_output(
                        output,
                        indent=6,
                        max_lines=config.max_output_lines,
                        max_chars=config.max_output_size,
                    )
                )
            else:
                print("    [ No Output ]")
            if error:
                print("    [ Error ]")
                print(
                    utils.misc.format_output(
                        error,
                        indent=6,
                        max_lines=config.max_output_lines,
                        max_chars=config.max_output_size,
                    )
                )
            if not self._ask_output_consent():
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
    source_path: str
    destination_path: str

    def _print(self, config):
        source_abs = utils.file.absolute_path(self.source_path)
        dest_abs = utils.file.absolute_path(self.destination_path)

        print("  [ Move ]")
        print(f'    comment: "{self.comment}"')
        print(f"    source: {self.source_path}")
        print(f"    real source: {source_abs}")
        print(f"    dest: {self.destination_path}")
        print(f"    real dest: {dest_abs}")

    def _create_error_result(self, error_message: str, accepted: bool) -> MoveResult:
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

    def _ask_move_consent(self) -> bool:
        """Ask user consent for move operation (user interaction - can be mocked)."""
        return utils.misc.ask_yes(
            f"    ? Allow moving '{self.source_path}' to '{self.destination_path}'? [y/N]: "
        )

    def _move_file_or_directory(self) -> None:
        """Move file or directory (OS interaction - can be mocked)."""
        utils.file.move_file_or_directory(self.source_path, self.destination_path)

    def _actually_solve(self, config: SolveigConfig) -> MoveResult:
        # Pre-flight validation
        abs_source_path = utils.file.absolute_path(self.source_path)
        abs_destination_path = utils.file.absolute_path(self.destination_path)

        try:
            self._validate_move_access()
        except (FileNotFoundError, PermissionError, OSError) as e:
            print(f"    Skipping - {e}")
            return MoveResult(
                requirement=self,
                accepted=False,
                error=str(e),
                source_path=abs_source_path,
                destination_path=abs_destination_path,
            )

        # Get user consent
        if self._ask_move_consent():
            try:
                # Perform the move operation
                self._move_file_or_directory()
                return MoveResult(
                    requirement=self,
                    accepted=True,
                    source_path=abs_source_path,
                    destination_path=abs_destination_path,
                )
            except (PermissionError, OSError, FileExistsError) as e:
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
    source_path: str
    destination_path: str

    def _print(self, config):
        source_abs = utils.file.absolute_path(self.source_path)
        dest_abs = utils.file.absolute_path(self.destination_path)

        print("  [ Copy ]")
        print(f'    comment: "{self.comment}"')
        print(f"    source: {self.source_path}")
        print(f"    real source: {source_abs}")
        print(f"    dest: {self.destination_path}")
        print(f"    real dest: {dest_abs}")

    def _create_error_result(self, error_message: str, accepted: bool) -> CopyResult:
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

    def _ask_copy_consent(self) -> bool:
        """Ask user consent for copy operation (user interaction - can be mocked)."""
        return utils.misc.ask_yes(
            f"    ? Allow copying '{self.source_path}' to '{self.destination_path}'? [y/N]: "
        )

    def _copy_file_or_directory(self) -> None:
        """Copy file or directory (OS interaction - can be mocked)."""
        utils.file.copy_file_or_directory(self.source_path, self.destination_path)

    def _actually_solve(self, config: SolveigConfig) -> CopyResult:
        # Pre-flight validation
        abs_source_path = utils.file.absolute_path(self.source_path)
        abs_destination_path = utils.file.absolute_path(self.destination_path)
        try:
            self._validate_copy_access()
        except (FileNotFoundError, PermissionError, OSError) as e:
            print(f"    Skipping - {e}")
            return CopyResult(
                requirement=self,
                accepted=False,
                error=str(e),
                source_path=abs_source_path,
                destination_path=abs_destination_path,
            )

        # Get user consent
        if self._ask_copy_consent():
            try:
                # Perform the copy operation
                self._copy_file_or_directory()
                return CopyResult(
                    requirement=self,
                    accepted=True,
                    source_path=abs_source_path,
                    destination_path=abs_destination_path,
                )
            except (PermissionError, OSError, FileExistsError) as e:
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
    path: str

    def _print(self, config):
        abs_path = utils.file.absolute_path(self.path)
        is_dir = abs_path.is_dir() if abs_path.exists() else False

        print("  [ Delete ]")
        print(f'    comment: "{self.comment}"')
        print(f"    path: {self.path} ({'directory' if is_dir else 'file'})")
        print(f"    real path: {abs_path}")
        print("    ⚠️  WARNING: This operation is permanent and cannot be undone!")

    def _create_error_result(self, error_message: str, accepted: bool) -> DeleteResult:
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

    def _ask_delete_consent(self) -> bool:
        """Ask user consent for delete operation (user interaction - can be mocked)."""
        return utils.misc.ask_yes(
            f"    ? ⚠️  PERMANENTLY DELETE '{self.path}'? This cannot be undone! [y/N]: "
        )

    def _delete_file_or_directory(self) -> None:
        """Delete file or directory (OS interaction - can be mocked)."""
        utils.file.delete_file_or_directory(self.path)

    def _actually_solve(self, config: SolveigConfig) -> DeleteResult:
        # Pre-flight validation
        abs_path = utils.file.absolute_path(self.path)
        try:
            self._validate_delete_access()
        except (FileNotFoundError, PermissionError) as e:
            print(f"    Skipping - {e}")
            return DeleteResult(
                requirement=self, accepted=False, error=str(e), path=abs_path
            )

        # Get user consent (with extra warning)
        if self._ask_delete_consent():
            try:
                # Perform the delete operation
                self._delete_file_or_directory()
                return DeleteResult(requirement=self, path=abs_path, accepted=True)
            except (PermissionError, OSError) as e:
                return DeleteResult(
                    requirement=self, accepted=False, error=str(e), path=abs_path
                )
        else:
            return DeleteResult(requirement=self, accepted=False, path=abs_path)
