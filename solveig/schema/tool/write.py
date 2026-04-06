"""Write tool - allows LLM to create/update files and directories."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, PrivateAttr, field_validator

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.result import WriteResult
from solveig.schema.tool.base import (
    BaseTool,
    validate_non_empty_path,
)
from solveig.utils.file import Filesystem, Metadata


class WriteTool(BaseTool):
    title: Literal["write"] = "write"
    path: str = Field(
        ...,
        description="File or directory path to create/update (supports ~ for home directory)",
    )
    is_directory: bool = Field(
        ..., description="If true, create a directory; if false, create a file"
    )
    content: str | None = Field(
        None, description="File content to write (only used when is_directory=false)"
    )

    _cached_metadata: Metadata | None = PrivateAttr(default=None)

    @field_validator("path")
    @classmethod
    def path_not_empty(cls, path: str) -> str:
        return validate_non_empty_path(path)

    async def display_header(self, interface: SolveigInterface) -> None:
        """Display write tool header."""
        await super().display_header(interface)
        self._cached_metadata = await self.display_path_info(
            interface, self.path, is_directory=self.is_directory
        )

    def create_error_result(self, error_message: str, accepted: bool) -> WriteResult:
        """Create WriteResult with error."""
        return WriteResult(
            tool=self,
            path=str(Filesystem.get_absolute_path(self.path)),
            accepted=accepted,
            error=error_message,
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of write capability."""
        return "write(comment, path, is_directory, content=null): creates a new file or directory, or updates an existing file. If it's a file, you may provide content to write."

    async def actually_solve(
        self, config: SolveigConfig, interface: SolveigInterface
    ) -> WriteResult:
        abs_path = Filesystem.get_absolute_path(self.path)

        # Write access validation
        try:
            await Filesystem.validate_write_access(
                path=abs_path,
                content=self.content,
                min_disk_size_left=config.min_disk_space_left,
            )
        except (OSError, PermissionError, IsADirectoryError) as e:
            await interface.display_error(f"Cannot write to {str(abs_path)}: {e}")
            return WriteResult(
                tool=self, path=str(abs_path), accepted=False, error=str(e)
            )

        already_exists = self._cached_metadata is not None or await Filesystem.exists(
            abs_path
        )

        if not self.is_directory and self.content:
            if already_exists:
                old = (await Filesystem.read_file(abs_path)).content.strip()
                await interface.display_diff(old_content=old, new_content=self.content)
            else:
                await interface.display_text_block(
                    self.content,
                    language=abs_path.suffix.lstrip("."),
                    title="Content",
                )

        auto_write = Filesystem.path_matches_patterns(
            abs_path, config.auto_allowed_paths
        )
        if auto_write:
            await interface.display_text(
                f"{'Updating' if already_exists else 'Creating'} {'directory' if self.is_directory else 'file'} since it matches config.auto_allowed_paths"
            )
        else:
            question = (
                f"Allow {'creating' if not already_exists else 'updating'} "
                f"{'directory' if self.is_directory else 'file'}?"
            )
            if not (await interface.ask_choice(question, ["Yes", "No"])) == 0:
                return WriteResult(tool=self, path=str(abs_path), accepted=False)

        try:
            if self.is_directory:
                await Filesystem.create_directory(abs_path)
            else:
                await Filesystem.write_file_text(abs_path, content=self.content or "")
            await interface.display_success(
                f"{'Updated' if already_exists else 'Created'}"
            )

            return WriteResult(tool=self, path=str(abs_path), accepted=True)

        except Exception as e:
            await interface.display_error(f"Found error when writing file: {e}")
            return WriteResult(
                tool=self,
                path=str(abs_path),
                accepted=False,
                error=f"Encoding error: {e}",
            )
