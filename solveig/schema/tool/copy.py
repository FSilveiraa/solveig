"""Copy tool - copies files and directories."""

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.tool._decorator import tool
from solveig.schema.tool._result import ToolResult
from solveig.utils.file import Filesystem
from solveig.utils.misc import validate_non_empty_path


@tool
async def copy(
    config: SolveigConfig,
    interface: SolveigInterface,
    source_path: str,
    destination_path: str,
) -> ToolResult:
    """Copy a file or directory.

    Args:
        source_path: Path of file/directory to copy from (supports ~ for home directory).
        destination_path: Path where file/directory should be copied to.
    """
    source_path = validate_non_empty_path(source_path)
    destination_path = validate_non_empty_path(destination_path)
    abs_source_path = Filesystem.get_absolute_path(source_path)
    abs_destination_path = Filesystem.get_absolute_path(destination_path)

    async with interface.with_group(
        f"Copy: {source_path} -> {destination_path}",
        auto_collapse=config.auto_collapse_tools,
    ):
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

        await interface.display_text(str(abs_source_path), prefix="Source:")
        await interface.display_text(str(abs_destination_path), prefix="Destination:")

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

        if auto_copy:
            await interface.display_info(
                f"Copying {'directory' if is_dir else 'file'} since both paths match config.auto_allowed_paths"
            )
        elif (
            await interface.ask_choice(
                f"Allow copying {'directory' if is_dir else 'file'}?", ["Yes", "No"]
            )
        ) != 0:
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
