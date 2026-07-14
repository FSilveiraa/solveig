"""Copy tool - copies files and directories."""

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field, field_validator
from pydantic_ai import RunContext
from pydantic_settings import CliPositionalArg

from solveig.context import SolveigContext
from solveig.subcommand.base import Subcommand
from solveig.tools.base import BaseTool
from solveig.tools.result import ToolResult
from solveig.utils.file import Filesystem
from solveig.utils.misc import validate_non_empty_path

if TYPE_CHECKING:
    from solveig.interface import SolveigInterface


class CopyTool(BaseTool):
    """Copy a file or directory."""

    subcommand: ClassVar[Subcommand] = Subcommand(commands=["/copy"])

    source_path: CliPositionalArg[str] = Field(
        description="Path of file/directory to copy from (supports ~ for home directory)."
    )
    destination_path: CliPositionalArg[str] = Field(
        description="Path where file/directory should be copied to."
    )

    @field_validator("source_path", "destination_path")
    @classmethod
    def _strip_path(cls, path: str) -> str:
        return validate_non_empty_path(path)

    @property
    def title(self) -> str:
        return f"Copy {self.source_path} -> {self.destination_path}"

    async def display_header(self, interface: "SolveigInterface") -> None:
        await interface.display_text(
            str(Filesystem.get_absolute_path(self.source_path)), prefix="Source:"
        )
        await interface.display_text(
            str(Filesystem.get_absolute_path(self.destination_path)),
            prefix="Destination:",
        )

    async def execute(self, ctx: RunContext[SolveigContext]) -> ToolResult:
        config, interface = ctx.deps.config, ctx.deps.interface
        abs_source_path = Filesystem.get_absolute_path(self.source_path)
        abs_destination_path = Filesystem.get_absolute_path(self.destination_path)

        for blocked in (abs_source_path, abs_destination_path):
            if Filesystem.path_matches_patterns(blocked, config.ignore_paths):
                await interface.display_error(
                    f"Path blocked by ignore_paths: {blocked}"
                )
                return ToolResult(issues=[f"path blocked by ignore_paths: {blocked}"])

        try:
            await Filesystem.validate_read_access(abs_source_path)
            await Filesystem.validate_write_access(abs_destination_path)
            is_dir = await Filesystem.is_dir(abs_source_path)
        except (FileNotFoundError, PermissionError, OSError) as e:
            await interface.display_error(
                f"Cannot copy from {abs_source_path} to {abs_destination_path}: {e}"
            )
            return ToolResult(issues=[e])

        auto_copy = Filesystem.path_matches_patterns(
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
        if auto_copy:
            await interface.display_info(
                f"Copying {noun} since both paths match config.auto_allowed_paths"
            )
        elif (await interface.ask_choice(f"Allow copying {noun}?", ["Yes", "No"])) != 0:
            await interface.display_warning("Rejected")
            return ToolResult(content="User declined the copy.")

        try:
            await Filesystem.copy(
                abs_source_path,
                abs_destination_path,
                min_space_left=config.min_disk_space_left,
            )
            await interface.display_success("Copied")
            return ToolResult(
                content=f"Copied {abs_source_path} to {abs_destination_path}"
            )
        except (PermissionError, OSError, FileExistsError) as e:
            await interface.display_error(f"Found error when copying: {e}")
            return ToolResult(issues=[e])
