"""Delete tool - permanently deletes files and directories."""

from pydantic_ai import RunContext
from pydantic_ai.messages import ToolReturn

from solveig.schema.deps import SolveigDeps
from solveig.schema.result import accepted, declined, failed
from solveig.schema.tool._validation import validate_non_empty_path
from solveig.utils.file import Filesystem


async def delete(ctx: RunContext[SolveigDeps], path: str) -> ToolReturn:
    """Permanently delete a file or directory.

    Args:
        path: Path of file/directory to permanently delete (supports ~ for home directory).
    """
    config = ctx.deps.config
    interface = ctx.deps.interface

    path = validate_non_empty_path(path)
    abs_path = Filesystem.get_absolute_path(path)

    async with interface.with_group(
        f"Delete: {path}", auto_collapse=config.auto_collapse_tools
    ):
        if Filesystem.path_matches_patterns(abs_path, config.ignore_paths):
            await interface.display_error(f"Path blocked by ignore_paths: {abs_path}")
            return failed(f"path blocked by ignore_paths: {abs_path}")

        try:
            is_directory = await Filesystem.is_dir(abs_path)
            await Filesystem.validate_delete_access(abs_path)
        except (FileNotFoundError, PermissionError, OSError) as e:
            await interface.display_error(f"Cannot delete {abs_path}: {e}")
            return failed(e)

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
            return declined("User declined the delete.")

        try:
            await Filesystem.delete(abs_path)
            await interface.display_success("Deleted")
            return accepted(f"Deleted {abs_path}")
        except (PermissionError, OSError) as e:
            await interface.display_error(f"Found error when deleting: {e}")
            return failed(e)
