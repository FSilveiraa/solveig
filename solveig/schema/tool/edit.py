"""Edit tool - allows LLM to edit files using string replacement."""

from typing import Literal

from pydantic import Field, field_validator

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.result import EditResult
from solveig.utils.file import Filesystem

from .base import BaseTool, validate_non_empty_path


class EditTool(BaseTool):
    """Edit files using exact string replacement."""

    title: Literal["edit"] = "edit"
    path: str = Field(
        ...,
        description="File path to edit (supports ~ for home directory)",
    )
    old_string: str = Field(
        ...,
        description="Exact string to find (including whitespace and indentation)",
    )
    new_string: str = Field(
        ...,
        description="String to replace with (can be empty for deletion)",
    )
    replace_all: bool = Field(
        default=False,
        description="Replace all occurrences (default: replace first only, error if multiple)",
    )

    @field_validator("path")
    @classmethod
    def path_not_empty(cls, path: str) -> str:
        return validate_non_empty_path(path)

    @field_validator("old_string")
    @classmethod
    def old_string_not_empty(cls, old_string: str) -> str:
        if not old_string:
            raise ValueError("old_string cannot be empty")
        return old_string

    async def display_header(self, interface: "SolveigInterface") -> None:
        """Display edit tool header."""
        await super().display_header(interface)
        await interface.display_file_info(source_path=self.path)

        # Show truncated preview of what we're replacing
        old_preview = (
            repr(self.old_string[:60] + "..." if len(self.old_string) > 60 else self.old_string)
        )
        new_preview = (
            repr(self.new_string[:60] + "..." if len(self.new_string) > 60 else self.new_string)
        )

        await interface.display_text(f"{old_preview}", prefix="Find:")
        await interface.display_text(f"{new_preview}", prefix="Replace:")

        if self.replace_all:
            await interface.display_text("(all occurrences)", prefix="Mode:")

    def create_error_result(self, error_message: str, accepted: bool) -> "EditResult":
        """Create EditResult with error."""
        return EditResult(
            tool=self,
            path=str(Filesystem.get_absolute_path(self.path)),
            accepted=accepted,
            error=error_message,
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of edit capability."""
        return (
            "edit(comment, path, old_string, new_string, replace_all=false): "
            "Edit a file by replacing exact string matches. "
            "old_string must exist in file. new_string can be empty for deletion. "
            "Errors if multiple occurrences found and replace_all=false."
        )

    async def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "EditResult":
        abs_path = Filesystem.get_absolute_path(self.path)

        # 1. Validate file exists and is readable/writable
        try:
            await Filesystem.validate_read_access(abs_path)
        except FileNotFoundError as e:
            await interface.display_error(f"File not found: {abs_path}")
            return self.create_error_result(str(e), accepted=False)
        except PermissionError as e:
            await interface.display_error(f"Cannot read {abs_path}: {e}")
            return self.create_error_result(str(e), accepted=False)

        if await Filesystem.is_dir(abs_path):
            await interface.display_error("Cannot edit a directory")
            return self.create_error_result("Cannot edit a directory", accepted=False)

        try:
            await Filesystem.validate_write_access(
                abs_path, min_disk_size_left=config.min_disk_space_left
            )
        except (PermissionError, OSError) as e:
            await interface.display_error(f"Cannot write to {abs_path}: {e}")
            return self.create_error_result(str(e), accepted=False)

        # 2. Read current content
        try:
            read_result = await Filesystem.read_file(abs_path)
            if read_result.encoding != "text":
                await interface.display_error("Cannot edit binary files")
                return self.create_error_result("Cannot edit binary files", accepted=False)
            original_content = read_result.content
        except Exception as e:
            await interface.display_error(f"Failed to read file: {e}")
            return self.create_error_result(str(e), accepted=False)

        # 3. Validate old_string exists
        occurrences = original_content.count(self.old_string)

        if occurrences == 0:
            await interface.display_error(
                f"String not found in file: {repr(self.old_string[:100])}"
            )
            return self.create_error_result(
                f"String not found: {repr(self.old_string[:60])}", accepted=False
            )

        if occurrences > 1 and not self.replace_all:
            await interface.display_error(
                f"String appears {occurrences} times. "
                f"Use replace_all=true or make the search string more specific."
            )
            return self.create_error_result(
                f"String appears {occurrences} times, replace_all=false",
                accepted=False,
            )

        # 4. Compute new content
        if self.replace_all:
            new_content = original_content.replace(self.old_string, self.new_string)
            replaced_count = occurrences
        else:
            new_content = original_content.replace(self.old_string, self.new_string, 1)
            replaced_count = 1

        # 5. Show diff/preview
        await interface.display_diff(
            old_content=original_content,
            new_content=new_content,
            title=f"Edit: {abs_path}",
        )

        # 6. Get approval
        auto_edit = Filesystem.path_matches_patterns(abs_path, config.auto_allowed_paths)

        if auto_edit:
            await interface.display_info(
                f"Auto-applying edit ({replaced_count} replacement(s)) since path is auto-allowed."
            )
            accepted = True
        else:
            choice = await interface.ask_choice(
                f"Apply edit ({replaced_count} replacement(s))?",
                ["Apply", "Cancel"],
            )
            accepted = choice == 0

        if not accepted:
            return EditResult(
                tool=self,
                path=str(abs_path),
                accepted=False,
                occurrences_found=occurrences,
                occurrences_replaced=0,
            )

        # 7. Apply edit
        try:
            await Filesystem.write_file(
                abs_path, new_content, min_space_left=config.min_disk_space_left
            )
            await interface.display_success(
                f"Edit applied: {replaced_count} replacement(s)"
            )
        except Exception as e:
            await interface.display_error(f"Failed to write file: {e}")
            return self.create_error_result(str(e), accepted=False)

        return EditResult(
            tool=self,
            path=str(abs_path),
            accepted=True,
            occurrences_found=occurrences,
            occurrences_replaced=replaced_count,
        )
