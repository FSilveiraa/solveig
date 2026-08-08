"""Move tool - moves files and directories."""

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field, field_validator
from pydantic_settings import CliPositionalArg

from solveig.interface.base import Level
from solveig.tools.base import BaseTool, ConsentDecision, check_path_security
from solveig.tools.result import ToolResult
from solveig.utils.file import Filesystem
from solveig.utils.misc import validate_non_empty_path

if TYPE_CHECKING:
    from solveig.config import SolveigConfig
    from solveig.interface.base import SolveigInterface


class MoveTool(BaseTool):
    """Move a file or directory."""

    subcommands: ClassVar[list[str]] = ["/move"]

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
        await interface.print(
            str(Filesystem.get_absolute_path(self.source_path)), prefix="Source:"
        )
        await interface.print(
            str(Filesystem.get_absolute_path(self.destination_path)),
            prefix="Destination:",
        )

    async def execute(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> ToolResult:
        abs_source_path = Filesystem.get_absolute_path(self.source_path)
        abs_destination_path = Filesystem.get_absolute_path(self.destination_path)

        for path in (self.source_path, self.destination_path):
            decision, abs_path = check_path_security(path, config)
            if decision == ConsentDecision.BLOCKED:
                await interface.print(
                    f"Path blocked by ignored_paths: {abs_path}", level=Level.ERROR
                )
                return ToolResult(issues=[f"path blocked by ignored_paths: {abs_path}"])

        try:
            await Filesystem.validate_read_access(abs_source_path)
            await Filesystem.validate_write_access(abs_destination_path)
            is_dir = await Filesystem.is_dir(abs_source_path)
        except (FileNotFoundError, PermissionError, OSError) as e:
            await interface.print(
                f"Cannot move from {abs_source_path} to {abs_destination_path}: {e}",
                level=Level.ERROR,
            )
            return ToolResult(issues=[e])

        auto_move = all(
            check_path_security(path, config)[0] == ConsentDecision.AUTO_ALLOWED
            for path in (self.source_path, self.destination_path)
        )

        dest_exists = not is_dir and await Filesystem.exists(abs_destination_path)
        if dest_exists:
            old = (await Filesystem.read_file(abs_destination_path)).content.strip()
            new = (await Filesystem.read_file(abs_source_path)).content.strip()
            await interface.add_diff_box(old_content=old, new_content=new)
            await interface.print("Overwriting existing file", level=Level.WARNING)

        noun = "directory" if is_dir else "file"
        if auto_move:
            await interface.print(
                f"Moving {noun} since both paths match config.auto_allowed_paths",
                level=Level.INFO,
            )
        elif (await interface.ask_choice(f"Allow moving {noun}?", ["Yes", "No"])) != 0:
            await interface.print("Rejected", level=Level.WARNING)
            return ToolResult(content="User declined the move.")

        try:
            await Filesystem.move(abs_source_path, abs_destination_path)
            await interface.print("Moved", level=Level.SUCCESS)
            return ToolResult(
                content=f"Moved {abs_source_path} to {abs_destination_path}"
            )
        except (PermissionError, OSError, FileExistsError) as e:
            await interface.print(f"Found error when moving: {e}", level=Level.ERROR)
            return ToolResult(issues=[e])
