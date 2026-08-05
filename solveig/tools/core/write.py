"""Write tool - creates or updates files and directories."""

from typing import TYPE_CHECKING

from pydantic import Field, field_validator

from solveig.interface.base import Level
from solveig.tools.base import BaseTool, ConsentDecision, check_path_security
from solveig.tools.result import ToolResult
from solveig.utils.file import Filesystem
from solveig.utils.misc import validate_non_empty_path

if TYPE_CHECKING:
    from solveig.config import SolveigConfig
    from solveig.interface.base import SolveigInterface


class WriteTool(BaseTool):
    """Create a new file or directory, or update an existing file."""

    path: str = Field(
        description="File or directory path to create/update (supports ~ for home directory)."
    )
    is_directory: bool = Field(
        description="If true, create a directory; if false, create a file."
    )
    content: str | None = Field(
        default=None,
        description="File content to write (only used when is_directory=false).",
    )

    @field_validator("path")
    @classmethod
    def _strip_path(cls, path: str) -> str:
        return validate_non_empty_path(path)

    @property
    def title(self) -> str:
        return f"Write {self.path}"

    async def display_header(self, interface: "SolveigInterface") -> None:
        await self.display_path_info(
            interface, self.path, is_directory=self.is_directory
        )

    async def execute(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> ToolResult:
        decision, abs_path = check_path_security(self.path, config)
        if decision == ConsentDecision.BLOCKED:
            await interface.print(
                f"Path blocked by ignored_paths: {abs_path}", level=Level.ERROR
            )
            return ToolResult(issues=[f"path blocked by ignored_paths: {abs_path}"])

        try:
            await Filesystem.validate_write_access(
                path=abs_path,
                content=self.content,
                min_disk_size_left=config.min_disk_space_left,
            )
        except (OSError, PermissionError, IsADirectoryError) as e:
            await interface.print(f"Cannot write to {abs_path}: {e}", level=Level.ERROR)
            return ToolResult(issues=[e])

        already_exists = await Filesystem.exists(abs_path)

        if not self.is_directory and self.content:
            if already_exists:
                old = (await Filesystem.read_file(abs_path)).content.strip()
                await interface.display_diff(old_content=old, new_content=self.content)
            else:
                await interface.add_text_box(
                    self.content, language=abs_path.suffix.lstrip("."), title="Content"
                )

        noun = "directory" if self.is_directory else "file"
        if decision == ConsentDecision.AUTO_ALLOWED:
            await interface.print(
                f"{'Updating' if already_exists else 'Creating'} "
                f"{noun} since it matches config.auto_allowed_paths"
            )
        else:
            question = (
                f"Allow {'creating' if not already_exists else 'updating'} {noun}?"
            )
            if (await interface.ask_choice(question, ["Yes", "No"])) != 0:
                await interface.print("Rejected", level=Level.WARNING)
                return ToolResult(content="User declined the write.")

        try:
            if self.is_directory:
                await Filesystem.create_directory(abs_path)
            else:
                await Filesystem.write_file_text(abs_path, content=self.content or "")
            await interface.print(
                "Updated" if already_exists else "Created", level=Level.SUCCESS
            )
            return ToolResult(
                content=f"{'Updated' if already_exists else 'Created'} {abs_path}"
            )
        except Exception as e:
            await interface.print(
                f"Found error when writing file: {e}", level=Level.ERROR
            )
            return ToolResult(issues=[e])
