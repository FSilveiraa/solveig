"""Edit tool - edits files using exact string replacement."""

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.result import ToolResult
from solveig.schema.tool._decorator import tool
from solveig.utils.file import Filesystem
from solveig.utils.misc import validate_non_empty_path


@tool
async def edit(
    config: SolveigConfig,
    interface: SolveigInterface,
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> ToolResult:
    """Edit a file by replacing exact string matches.

    old_string must exist in the file. new_string can be empty for deletion.
    Errors if multiple occurrences are found and replace_all=false.

    Args:
        path: File path to edit (supports ~ for home directory).
        old_string: Exact string to find (including whitespace and indentation).
        new_string: String to replace with (can be empty for deletion).
        replace_all: Replace all occurrences (default: replace first only, error if multiple).
    """
    path = validate_non_empty_path(path)
    if not old_string:
        raise ValueError("old_string cannot be empty")

    abs_path = Filesystem.get_absolute_path(path)

    async with interface.with_group(
        f"Edit: {path}", auto_collapse=config.auto_collapse_tools
    ):
        if Filesystem.path_matches_patterns(abs_path, config.ignore_paths):
            await interface.display_error(f"Path blocked by ignore_paths: {abs_path}")
            return ToolResult(issues=[f"path blocked by ignore_paths: {abs_path}"])

        old_preview = repr(
            old_string[:60] + "..." if len(old_string) > 60 else old_string
        )
        new_preview = repr(
            new_string[:60] + "..." if len(new_string) > 60 else new_string
        )
        await interface.display_text(old_preview, prefix="Find:")
        await interface.display_text(new_preview, prefix="Replace:")
        if replace_all:
            await interface.display_text("(all occurrences)", prefix="Mode:")

        # 1. Validate file exists and is readable/writable
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

        # 2. Read current content
        try:
            read_result = await Filesystem.read_file(abs_path)
            if read_result.encoding != "text":
                await interface.display_error("Cannot edit binary files")
                return ToolResult(issues=["cannot edit binary files"])
            original_content = read_result.content
        except Exception as e:
            await interface.display_error(f"Failed to read file: {e}")
            return ToolResult(issues=[e])

        # 3. Validate old_string exists
        occurrences_found = original_content.count(old_string)
        if occurrences_found == 0:
            await interface.display_error(f"String not found in file: {old_preview}")
            return ToolResult(issues=[f"string not found: {old_preview}"])
        if occurrences_found > 1 and not replace_all:
            await interface.display_error(
                f"String appears {occurrences_found} times. "
                f"Use replace_all=true or make the search string more specific."
            )
            return ToolResult(
                issues=[f"string appears {occurrences_found} times, replace_all=false"]
            )
        occurrences_replaced = occurrences_found if replace_all else 1

        # 4. Compute new content and show diff
        if replace_all:
            new_content = original_content.replace(old_string, new_string)
        else:
            new_content = original_content.replace(old_string, new_string, 1)
        await interface.display_diff(
            old_content=original_content,
            new_content=new_content,
            title=f"Edit: {abs_path}",
        )

        # 5. Get approval
        auto_edit = Filesystem.path_matches_patterns(
            abs_path, config.auto_allowed_paths
        )
        if auto_edit:
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

        # 6. Apply edit
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
