"""Write tool - creates or updates files and directories."""

from pydantic_ai import RunContext

from solveig.context import SolveigContext
from solveig.tools.result import ToolResult
from solveig.utils.file import Filesystem
from solveig.utils.misc import validate_non_empty_path


async def write(
    ctx: RunContext[SolveigContext],
    path: str,
    is_directory: bool,
    content: str | None = None,
) -> ToolResult:
    """Create a new file or directory, or update an existing file.

    Args:
        path: File or directory path to create/update (supports ~ for home directory).
        is_directory: If true, create a directory; if false, create a file.
        content: File content to write (only used when is_directory=false).
    """
    config, interface = ctx.deps.config, ctx.deps.interface
    path = validate_non_empty_path(path)
    abs_path = Filesystem.get_absolute_path(path)

    async with interface.with_group(
        f"Write: {path}", auto_collapse=config.auto_collapse_tools
    ):
        if Filesystem.path_matches_patterns(abs_path, config.ignore_paths):
            await interface.display_error(f"Path blocked by ignore_paths: {abs_path}")
            return ToolResult(issues=[f"path blocked by ignore_paths: {abs_path}"])

        try:
            await Filesystem.validate_write_access(
                path=abs_path,
                content=content,
                min_disk_size_left=config.min_disk_space_left,
            )
        except (OSError, PermissionError, IsADirectoryError) as e:
            await interface.display_error(f"Cannot write to {abs_path}: {e}")
            return ToolResult(issues=[e])

        already_exists = await Filesystem.exists(abs_path)

        if not is_directory and content:
            if already_exists:
                old = (await Filesystem.read_file(abs_path)).content.strip()
                await interface.display_diff(old_content=old, new_content=content)
            else:
                await interface.display_text_box(
                    content, language=abs_path.suffix.lstrip("."), title="Content"
                )

        auto_write = Filesystem.path_matches_patterns(
            abs_path, config.auto_allowed_paths
        )
        if auto_write:
            await interface.display_text(
                f"{'Updating' if already_exists else 'Creating'} "
                f"{'directory' if is_directory else 'file'} since it matches config.auto_allowed_paths"
            )
        else:
            question = (
                f"Allow {'creating' if not already_exists else 'updating'} "
                f"{'directory' if is_directory else 'file'}?"
            )
            if (await interface.ask_choice(question, ["Yes", "No"])) != 0:
                await interface.display_warning("Rejected")
                return ToolResult(content="User declined the write.")

        try:
            if is_directory:
                await Filesystem.create_directory(abs_path)
            else:
                await Filesystem.write_file_text(abs_path, content=content or "")
            await interface.display_success("Updated" if already_exists else "Created")
            return ToolResult(
                content=f"{'Updated' if already_exists else 'Created'} {abs_path}"
            )
        except Exception as e:
            await interface.display_error(f"Found error when writing file: {e}")
            return ToolResult(issues=[e])
