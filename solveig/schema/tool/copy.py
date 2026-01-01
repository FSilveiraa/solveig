"""Copy tool - allows LLM to copy files and directories."""

from typing import Literal

from pydantic import Field, field_validator

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.result import CopyResult
from solveig.utils.file import Filesystem

from .base import BaseTool, validate_non_empty_path


class CopyTool(BaseTool):
    title: Literal["copy"] = "copy"
    source_path: str = Field(
        ...,
        description="Path of file/directory to copy from (supports ~ for home directory)",
    )
    destination_path: str = Field(
        ..., description="Path where file/directory should be copied to"
    )

    @field_validator("source_path", "destination_path", mode="before")
    @classmethod
    def validate_paths(cls, path: str) -> str:
        return validate_non_empty_path(path)

    async def display_header(self, interface: "SolveigInterface") -> None:
        """Display copy tool header."""
        await super().display_header(interface)
        await interface.display_file_info(
            source_path=self.source_path,
            destination_path=self.destination_path,
        )

    def create_error_result(self, error_message: str, accepted: bool) -> "CopyResult":
        """Create CopyResult with error."""
        return CopyResult(
            tool=self,
            accepted=accepted,
            error=error_message,
            source_path=str(Filesystem.get_absolute_path(self.source_path)),
            destination_path=str(Filesystem.get_absolute_path(self.destination_path)),
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of copy capability."""
        return (
            "copy(comment, source_path, destination_path): copies a file or directory"
        )

    async def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "CopyResult":
        # Pre-flight validation - use utils/file.py validation
        abs_source_path = Filesystem.get_absolute_path(self.source_path)
        abs_destination_path = Filesystem.get_absolute_path(self.destination_path)

        try:
            await Filesystem.validate_read_access(abs_source_path)
            await Filesystem.validate_write_access(abs_destination_path)
            is_dir = await Filesystem.is_dir(abs_source_path)
        except (FileNotFoundError, PermissionError, OSError) as e:
            await interface.display_error(
                f"Cannot copy from {str(abs_source_path)} to {str(abs_destination_path)}: {e}"
            )
            return CopyResult(
                tool=self,
                accepted=False,
                error=str(e),
                source_path=str(abs_source_path),
                destination_path=str(abs_destination_path),
            )
        # Check for auto-allowed paths
        auto_copy = Filesystem.path_matches_patterns(
            abs_source_path, config.auto_allowed_paths
        ) and Filesystem.path_matches_patterns(
            abs_destination_path, config.auto_allowed_paths
        )

        if auto_copy:
            await interface.display_info(
                f"Copying {'directory' if is_dir else 'file'} since both paths match config.auto_allowed_paths"
            )
        elif (
            await interface.ask_choice(
                f"Allow copying {'directory' if is_dir else 'file'}?", ["Yes", "No"]
            )
            != 0
        ):
            return CopyResult(
                tool=self,
                accepted=False,
                source_path=str(abs_source_path),
                destination_path=str(abs_destination_path),
            )

        try:
            # Perform the copy operation - use utils/file.py method
            await Filesystem.copy(
                abs_source_path,
                abs_destination_path,
                min_space_left=config.min_disk_space_left,
            )
            await interface.display_success("Copied")
            return CopyResult(
                tool=self,
                accepted=True,
                source_path=str(abs_source_path),
                destination_path=str(abs_destination_path),
            )
        except (PermissionError, OSError, FileExistsError) as e:
            await interface.display_error(f"Found error when copying: {e}")
            return CopyResult(
                tool=self,
                accepted=False,
                error=str(e),
                source_path=str(abs_source_path),
                destination_path=str(abs_destination_path),
            )
