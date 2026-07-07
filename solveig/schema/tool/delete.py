"""Delete tool - permanently deletes files and directories."""

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.tool.contract import ToolResult, tool
from solveig.utils.file import Filesystem
from solveig.utils.misc import validate_non_empty_path


@tool
async def delete(
    config: SolveigConfig, interface: SolveigInterface, path: str
) -> ToolResult:
    """Permanently delete a file or directory.

    Args:
        path: Path of file/directory to permanently delete (supports ~ for home directory).
    """
    path = validate_non_empty_path(path)
    abs_path = Filesystem.get_absolute_path(path)

    async with interface.with_group(
        f"Delete: {path}", auto_collapse=config.auto_collapse_tools
    ):
        if Filesystem.path_matches_patterns(abs_path, config.ignore_paths):
            await interface.display_error(f"Path blocked by ignore_paths: {abs_path}")
            return ToolResult(issues=[f"path blocked by ignore_paths: {abs_path}"])

        try:
            is_directory = await Filesystem.is_dir(abs_path)
            await Filesystem.validate_delete_access(abs_path)
        except (FileNotFoundError, PermissionError, OSError) as e:
            await interface.display_error(f"Cannot delete {abs_path}: {e}")
            return ToolResult(issues=[e])

        await interface.display_warning(
            "This operation is permanent and cannot be undone!"
        )

        auto_delete = Filesystem.path_matches_patterns(
            abs_path, config.auto_allowed_paths
        )
        if auto_delete:
            await interface.display_info(
                f"Deleting {'directory' if is_directory else 'file'} since it matches config.auto_allowed_paths"
            )
        elif (
            await interface.ask_choice(
                f"Delete {'directory' if is_directory else 'file'}?", ["Yes", "No"]
            )
        ) != 0:
            await interface.display_warning("Rejected")
            return ToolResult(content="User declined the delete.")

        try:
            await Filesystem.delete(abs_path)
            await interface.display_success("Deleted")
            return ToolResult(content=f"Deleted {abs_path}")
        except (PermissionError, OSError) as e:
            await interface.display_error(f"Found error when deleting: {e}")
            return ToolResult(issues=[e])
