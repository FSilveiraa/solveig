"""Move tool - moves files and directories."""

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field, field_validator
from pydantic_settings import CliPositionalArg

from solveig.subcommand.base import Subcommand
from solveig.tools.base import BaseTool
from solveig.tools.result import ToolResult
from solveig.utils.file import Filesystem
from solveig.utils.misc import validate_non_empty_path

if TYPE_CHECKING:
    from solveig.config import SolveigConfig
    from solveig.interface import SolveigInterface


class MoveTool(BaseTool):
    """Move a file or directory."""

    subcommand: ClassVar[Subcommand] = Subcommand(commands=["/move"])

    source_path: CliPositionalArg[str] = Field(
        description="Current path of file/directory to move (supports ~ for home directory)."
    )
    destination_path: CliPositionalArg[str] = Field(
        description="New path where file/directory should be moved to."
    )

    @field_validator("source_path", "destination_path")
    @classmethod
    def _strip_path(cls, path: str) -> str:
        return validate_non_empty_path(path)

    @property
    def title(self) -> str:
        return f"Move {self.source_path} → {self.destination_path}"

    async def display_header(self, interface: "SolveigInterface") -> None:
        await interface.display_text(
            str(Filesystem.get_absolute_path(self.source_path)), prefix="Source:"
        )
        await interface.display_text(
            str(Filesystem.get_absolute_path(self.destination_path)),
            prefix="Destination:",
        )

    async def execute(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> ToolResult:
        abs_source_path = Filesystem.get_absolute_path(self.source_path)
        abs_destination_path = Filesystem.get_absolute_path(self.destination_path)

        for blocked in (abs_source_path, abs_destination_path):
            if Filesystem.path_matches_patterns(blocked, config.ignored_paths):
                await interface.display_error(
                    f"Path blocked by ignored_paths: {blocked}"
                )
                return ToolResult(issues=[f"path blocked by ignored_paths: {blocked}"])

        try:
            await Filesystem.validate_read_access(abs_source_path)
            await Filesystem.validate_write_access(abs_destination_path)
            is_dir = await Filesystem.is_dir(abs_source_path)
        except (FileNotFoundError, PermissionError, OSError) as e:
            await interface.display_error(
                f"Cannot move from {abs_source_path} to {abs_destination_path}: {e}"
            )
            return ToolResult(issues=[e])

        auto_move = Filesystem.path_matches_patterns(
            abs_source_path, config.auto_allowed_paths
        ) and Filesystem.path_matches_patterns(
            abs_destination_path, config.auto_allowed_paths
        )

        dest_exists = not is_dir and await Filesystem.exists(abs_destination_path)
        if dest_exists:
            old = (await Filesystem.read_file(abs_destination_path)).content.strip()
            new = (await Filesystem.read_file(abs_source_path)).content.strip()
            await interface.display_diff(old_content=old, new_content=new)
            await interface.display_warning("Overwriting existing file")

        noun = "directory" if is_dir else "file"
        if auto_move:
            await interface.display_info(
                f"Moving {noun} since both paths match config.auto_allowed_paths"
            )
        elif (await interface.ask_choice(f"Allow moving {noun}?", ["Yes", "No"])) != 0:
            await interface.display_warning("Rejected")
            return ToolResult(content="User declined the move.")

        try:
            await Filesystem.move(abs_source_path, abs_destination_path)
            await interface.display_success("Moved")
            return ToolResult(
                content=f"Moved {abs_source_path} to {abs_destination_path}"
            )
        except (PermissionError, OSError, FileExistsError) as e:
            await interface.display_error(f"Found error when moving: {e}")
            return ToolResult(issues=[e])
