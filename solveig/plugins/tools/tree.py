"""Tree plugin tool - generates directory tree listings."""

from pydantic_ai import RunContext
from pydantic_ai.messages import ToolReturn

from solveig.schema.deps import SolveigDeps
from solveig.schema.result import accepted, declined, failed
from solveig.schema.tool._validation import validate_non_empty_path
from solveig.utils.file import Filesystem


async def tree(
    ctx: RunContext[SolveigDeps],
    path: str,
    max_depth: int = -1,
) -> ToolReturn:
    """Generate a directory tree listing showing file structure.

    Args:
        path: Directory path to generate tree for (supports ~ for home directory).
        max_depth: Maximum depth to explore (-1 for full tree).
    """
    config = ctx.deps.config
    interface = ctx.deps.interface

    path = validate_non_empty_path(path)
    abs_path = Filesystem.get_absolute_path(path)

    async with interface.with_group(
        f"Tree: {path}", auto_collapse=config.auto_collapse_tools
    ):
        if Filesystem.path_matches_patterns(abs_path, config.ignore_paths):
            await interface.display_error(f"Path blocked by ignore_paths: {abs_path}")
            return failed(f"path blocked by ignore_paths: {abs_path}")

        try:
            await Filesystem.validate_read_access(abs_path)
        except (FileNotFoundError, PermissionError, IsADirectoryError) as e:
            await interface.display_error(f"Cannot access {abs_path}: {e}")
            return failed(e)

        choice_read_tree = await interface.ask_choice(
            "Allow reading tree?",
            [
                "Read and send tree",
                "Read tree and inspect first",
                "Don't read anything",
            ],
        )

        if choice_read_tree > 1:
            await interface.display_warning("Rejected")
            return declined("User declined to read the tree.")

        metadata = await Filesystem.read_metadata(abs_path, descend_level=max_depth)
        await interface.display_tree(
            metadata=metadata, display_metadata=False, title=f"Tree: {abs_path}"
        )

        path_matches = Filesystem.path_matches_patterns(
            abs_path, config.auto_allowed_paths
        )
        if path_matches or choice_read_tree == 0:
            if path_matches and choice_read_tree != 0:
                await interface.display_info(
                    f"Sending tree since {abs_path} matches config.auto_allowed_paths"
                )
            allow_send = True
        else:
            allow_send = (
                await interface.ask_choice("Allow sending tree?", ["Yes", "No"]) == 0
            )

        if not allow_send:
            await interface.display_warning("Rejected")
            return declined("User declined to send the tree.")

        await interface.display_success("Accepted")
        return accepted(metadata)
