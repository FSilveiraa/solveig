"""Delete tool - permanently deletes files and directories."""

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field, field_validator
from pydantic_settings import CliPositionalArg

from solveig.subcommands.base import Subcommand
from solveig.tools.base import BaseTool, ConsentDecision, check_path_security
from solveig.tools.result import ToolResult
from solveig.utils.file import Filesystem
from solveig.utils.misc import validate_non_empty_path

if TYPE_CHECKING:
    from solveig.config import SolveigConfig
    from solveig.interface import SolveigInterface


class DeleteTool(BaseTool):
    """Permanently delete a file or directory."""

    subcommand: ClassVar[Subcommand] = Subcommand(commands=["/delete"])

    path: CliPositionalArg[str] = Field(
        description="Path of file/directory to permanently delete (supports ~ for home directory)."
    )

    @field_validator("path")
    @classmethod
    def _strip_path(cls, path: str) -> str:
        return validate_non_empty_path(path)

    @property
    def title(self) -> str:
        return f"Delete {self.path}"

    async def display_header(self, interface: "SolveigInterface") -> None:
        await self.display_path_info(interface, self.path)

    async def execute(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> ToolResult:
        decision, abs_path = check_path_security(self.path, config)
        if decision == ConsentDecision.BLOCKED:
            await interface.display_error(f"Path blocked by ignored_paths: {abs_path}")
            return ToolResult(issues=[f"path blocked by ignored_paths: {abs_path}"])

        try:
            is_directory = await Filesystem.is_dir(abs_path)
            await Filesystem.validate_delete_access(abs_path)
        except (FileNotFoundError, PermissionError, OSError) as e:
            await interface.display_error(f"Cannot delete {abs_path}: {e}")
            return ToolResult(issues=[e])

        await interface.display_warning(
            "This operation is permanent and cannot be undone!"
        )

        noun = "directory" if is_directory else "file"
        if decision == ConsentDecision.AUTO_ALLOWED:
            await interface.display_info(
                f"Deleting {noun} since it matches config.auto_allowed_paths"
            )
        elif (await interface.ask_choice(f"Delete {noun}?", ["Yes", "No"])) != 0:
            await interface.display_warning("Rejected")
            return ToolResult(content="User declined the delete.")

        try:
            await Filesystem.delete(abs_path)
            await interface.display_success("Deleted")
            return ToolResult(content=f"Deleted {abs_path}")
        except (PermissionError, OSError) as e:
            await interface.display_error(f"Found error when deleting: {e}")
            return ToolResult(issues=[e])
