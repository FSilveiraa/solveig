"""Move tool - allows LLM to move files and directories."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from pydantic import Field, PrivateAttr, field_validator

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.result import MoveResult
from solveig.utils.file import Filesystem, Metadata

from .base import BaseTool, Positional, Subcommand, validate_non_empty_path


class MoveTool(BaseTool):
    type: Literal["move"] = "move"
    subcommand: ClassVar[Subcommand] = Subcommand(
        commands=["/move", "/mv"],
    )

    source_path: Annotated[str, Positional(0)] = Field(
        ...,
        description="Current path of file/directory to move (supports ~ for home directory)",
    )
    destination_path: Annotated[str, Positional(1)] = Field(
        ..., description="New path where file/directory should be moved to"
    )

    @field_validator("source_path", "destination_path", mode="before")
    @classmethod
    def validate_paths(cls, path: str) -> str:
        return validate_non_empty_path(path)

    _cached_source_metadata: Metadata | None = PrivateAttr(default=None)
    _cached_dest_metadata: Metadata | None = PrivateAttr(default=None)

    async def display_header(self, interface: SolveigInterface) -> None:
        """Display move tool header."""
        await super().display_header(interface)
        self._cached_source_metadata = await self.display_path_info(
            interface, self.source_path, prefix="Source:     "
        )
        self._cached_dest_metadata = await self.display_path_info(
            interface, self.destination_path, prefix="Destination:"
        )

    def create_error_result(self, error_message: str, accepted: bool) -> MoveResult:
        """Create MoveResult with error."""
        return MoveResult(
            tool=self,
            accepted=accepted,
            error=error_message,
            source_path=str(Filesystem.get_absolute_path(self.source_path)),
            destination_path=str(Filesystem.get_absolute_path(self.destination_path)),
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of move capability."""
        return "move(comment, source_path, destination_path): moves a file or directory"

    async def actually_solve(
        self, config: SolveigConfig, interface: SolveigInterface
    ) -> MoveResult:
        abs_source_path = Filesystem.get_absolute_path(self.source_path)
        abs_destination_path = Filesystem.get_absolute_path(self.destination_path)

        for blocked in (abs_source_path, abs_destination_path):
            if Filesystem.path_matches_patterns(blocked, config.ignore_paths):
                return self.create_error_result(
                    f"Path blocked by ignore_paths: {blocked}", accepted=False
                )

        try:
            await Filesystem.validate_read_access(abs_source_path)
            await Filesystem.validate_write_access(abs_destination_path)
            is_dir = (
                self._cached_source_metadata.is_directory
                if self._cached_source_metadata
                else await Filesystem.is_dir(abs_source_path)
            )
        except (FileNotFoundError, PermissionError, OSError) as e:
            await interface.display_error(
                f"Cannot move from {str(abs_source_path)} to {str(abs_destination_path)}: {e}"
            )
            return MoveResult(
                tool=self,
                accepted=False,
                error=str(e),
                source_path=str(abs_source_path),
                destination_path=str(abs_destination_path),
            )

        # Check for auto-allowed paths
        auto_move = Filesystem.path_matches_patterns(
            abs_source_path, config.auto_allowed_paths
        ) and Filesystem.path_matches_patterns(
            abs_destination_path, config.auto_allowed_paths
        )

        if not is_dir and self._cached_dest_metadata is not None:
            old = (await Filesystem.read_file(abs_destination_path)).content.strip()
            new = (await Filesystem.read_file(abs_source_path)).content.strip()
            await interface.display_diff(old_content=old, new_content=new)
            await interface.display_warning("Overwriting existing file")

        if auto_move:
            await interface.display_info(
                f"Moving {'directory' if is_dir else 'file'} since both paths match config.auto_allowed_paths"
            )
        elif (
            await interface.ask_choice(
                f"Allow moving {'directory' if is_dir else 'file'}?", ["Yes", "No"]
            )
            != 0
        ):
            return MoveResult(
                tool=self,
                accepted=False,
                source_path=str(abs_source_path),
                destination_path=str(abs_destination_path),
            )

        try:
            # Perform the move operation - use utils/file.py method
            await Filesystem.move(abs_source_path, abs_destination_path)
            await interface.display_success("Moved")
            return MoveResult(
                tool=self,
                accepted=True,
                source_path=str(abs_source_path),
                destination_path=str(abs_destination_path),
            )
        except (PermissionError, OSError, FileExistsError) as e:
            await interface.display_error(f"Found error when moving: {e}")
            return MoveResult(
                tool=self,
                accepted=False,
                error=str(e),
                source_path=str(abs_source_path),
                destination_path=str(abs_destination_path),
            )
