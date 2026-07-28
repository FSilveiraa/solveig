"""Edit tool - edits files using exact string replacement."""

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field, field_validator
from pydantic_settings import CliPositionalArg

from solveig.config import SolveigConfig
from solveig.subcommands.base import Subcommand
from solveig.tools.base import BaseTool
from solveig.tools.result import ToolResult
from solveig.utils.file import Filesystem
from solveig.utils.misc import validate_non_empty_path

if TYPE_CHECKING:
    from anyio import Path

    from solveig.interface import SolveigInterface


def _preview(text: str) -> str:
    return repr(text[:60] + "..." if len(text) > 60 else text)


class EditTool(BaseTool):
    """Edit a file by replacing exact string matches.

    old_string must exist in the file. new_string can be empty for deletion.
    Errors if multiple occurrences are found and replace_all=false.
    """

    subcommand: ClassVar[Subcommand] = Subcommand(commands=["/edit"])

    path: CliPositionalArg[str] = Field(
        description="File path to edit (supports ~ for home directory)."
    )
    old_string: CliPositionalArg[str] = Field(
        description="Exact string to find (including whitespace and indentation)."
    )
    new_string: CliPositionalArg[str] = Field(
        description="String to replace with (can be empty for deletion)."
    )
    replace_all: bool = Field(
        default=False,
        description="Replace all occurrences (default: replace first only, error if multiple).",
    )

    @field_validator("path")
    @classmethod
    def _strip_path(cls, path: str) -> str:
        return validate_non_empty_path(path)

    @property
    def title(self) -> str:
        return f"Edit {self.path}"

    async def display_header(self, interface: "SolveigInterface") -> None:
        await self.display_path_info(interface, self.path)
        await interface.display_text(_preview(self.old_string), prefix="Find:")
        await interface.display_text(_preview(self.new_string), prefix="Replace:")
        if self.replace_all:
            await interface.display_text("(all occurrences)", prefix="Mode:")

    async def execute(
        self, config: SolveigConfig, interface: "SolveigInterface"
    ) -> ToolResult:
        if not self.old_string:
            raise ValueError("old_string cannot be empty")

        abs_path = Filesystem.get_absolute_path(self.path)

        access_error = await self._validate_access(interface, config, abs_path)
        if access_error is not None:
            return access_error

        prepared = await self._load_and_prepare(interface, abs_path)
        if isinstance(prepared, ToolResult):  # error
            return prepared
        original_content, new_content, occurrences = prepared

        await interface.display_diff(
            old_content=original_content,
            new_content=new_content,
            title=f"Edit: {abs_path}",
        )
        return await self._apply(interface, config, abs_path, new_content, occurrences)

    async def _validate_access(
        self, interface: "SolveigInterface", config: SolveigConfig, abs_path: "Path"
    ) -> ToolResult | None:
        """Reject the edit up front (blocked path, unreadable, directory, or
        unwritable); return the error `ToolResult`, or `None` to proceed."""
        if Filesystem.path_matches_patterns(abs_path, config.ignored_paths):
            await interface.display_error(f"Path blocked by ignored_paths: {abs_path}")
            return ToolResult(issues=[f"path blocked by ignored_paths: {abs_path}"])
        try:
            await Filesystem.validate_read_access(abs_path)
        except (FileNotFoundError, PermissionError) as e:
            await interface.display_error(f"Cannot read {abs_path}: {e}")
            return ToolResult(issues=[e])
        if await Filesystem.is_dir(abs_path):
            await interface.display_error("Cannot edit a directory")
            return ToolResult(issues=["cannot edit a directory"])
        try:
            await Filesystem.validate_write_access(
                abs_path, min_disk_size_left=config.min_disk_space_left
            )
        except (PermissionError, OSError) as e:
            await interface.display_error(f"Cannot write to {abs_path}: {e}")
            return ToolResult(issues=[e])
        return None

    async def _load_and_prepare(
        self, interface: "SolveigInterface", abs_path: "Path"
    ) -> "tuple[str, str, int] | ToolResult":
        """Read the file and locate `old_string`; return
        `(original, new_content, occurrences_replaced)`, or an error
        `ToolResult` (binary file, string missing, or ambiguous match)."""
        try:
            read_result = await Filesystem.read_file(abs_path)
            if read_result.encoding != "text":
                await interface.display_error("Cannot edit binary files")
                return ToolResult(issues=["cannot edit binary files"])
            original_content = read_result.content
        except Exception as e:
            await interface.display_error(f"Failed to read file: {e}")
            return ToolResult(issues=[e])

        occurrences_found = original_content.count(self.old_string)
        if occurrences_found == 0:
            await interface.display_error(
                f"String not found in file: {_preview(self.old_string)}"
            )
            return ToolResult(issues=[f"string not found: {_preview(self.old_string)}"])
        if occurrences_found > 1 and not self.replace_all:
            await interface.display_error(
                f"String appears {occurrences_found} times. "
                f"Use replace_all=true or make the search string more specific."
            )
            return ToolResult(
                issues=[f"string appears {occurrences_found} times, replace_all=false"]
            )

        occurrences_replaced = occurrences_found if self.replace_all else 1
        new_content = original_content.replace(
            self.old_string, self.new_string, -1 if self.replace_all else 1
        )
        return original_content, new_content, occurrences_replaced

    async def _apply(
        self,
        interface: "SolveigInterface",
        config: SolveigConfig,
        abs_path: "Path",
        new_content: str,
        occurrences_replaced: int,
    ) -> ToolResult:
        """Get approval (auto-allowed paths bypass it) and write the file."""
        if Filesystem.path_matches_patterns(abs_path, config.auto_allowed_paths):
            await interface.display_info(
                f"Auto-applying edit ({occurrences_replaced} replacement(s)) since path is auto-allowed."
            )
        elif (
            await interface.ask_choice(
                f"Apply edit ({occurrences_replaced} replacement(s))?", ["Yes", "No"]
            )
        ) != 0:
            await interface.display_warning("Rejected")
            return ToolResult(content="User declined the edit.")

        try:
            await Filesystem.write_file_text(
                abs_path, new_content, min_space_left=config.min_disk_space_left
            )
            await interface.display_success(
                f"Edit applied: {occurrences_replaced} replacement(s)"
            )
            return ToolResult(
                content=f"Edited {abs_path}: {occurrences_replaced} replacement(s)"
            )
        except Exception as e:
            await interface.display_error(f"Failed to write file: {e}")
            return ToolResult(issues=[e])
