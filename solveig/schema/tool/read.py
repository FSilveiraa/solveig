"""Read tool - reads files and directories."""

from anyio import Path

from solveig.interface import SolveigInterface
from solveig.schema.deps import SolveigContext
from solveig.schema.tool.result import ToolResult
from solveig.utils.file import FileMetadata, Filesystem
from solveig.utils.misc import validate_non_empty_path


def _validate_line_ranges(ranges: list[list[int]]) -> None:
    if len(ranges) > 3:
        raise ValueError("Maximum 3 line ranges allowed")
    for i, range_list in enumerate(ranges):
        if len(range_list) != 2:
            raise ValueError(
                f"Range {i + 1}: Must have exactly 2 elements [start, end]"
            )
        start, end = range_list
        if start < 1:
            raise ValueError(f"Range {i + 1}: Start line must be >= 1")
        if end != -1 and end < start:
            raise ValueError(f"Range {i + 1}: End line must be >= start line or -1")


async def _read_metadata_only(
    interface: SolveigInterface, path_matches: bool, metadata: FileMetadata
) -> ToolResult:
    """Directory or metadata_only request: offer to send just the file/dir metadata."""
    if metadata.is_directory:
        await interface.display_tree(metadata=metadata)

    if path_matches:
        await interface.display_info("Sending metadata since path is auto-allowed.")
        send_metadata = True
    else:
        send_metadata = (
            await interface.ask_choice("Send metadata to assistant?", ["Yes", "No"])
            == 0
        )

    if not send_metadata:
        await interface.display_warning("Rejected")
        return ToolResult(content="User declined to send metadata.")

    await interface.display_success("Accepted")
    return ToolResult(content=metadata)


async def _read_content(
    interface: SolveigInterface,
    abs_path: Path,
    path_matches: bool,
    line_ranges: list[list[int]] | None,
    metadata: FileMetadata,
) -> ToolResult:
    """File content request: negotiate depth of access, read, display, then send."""
    if line_ranges:
        request_desc = ", ".join(f"{start} to {end}" for start, end in line_ranges)
        await interface.display_text(
            f"Lines {request_desc} and metadata", prefix="Requesting:"
        )
    else:
        await interface.display_text("Content and metadata", prefix="Requesting:")

    if path_matches:
        await interface.display_info(
            "Reading and sending file since path is auto-allowed."
        )
        choice = 0  # "Read and send"
    else:
        choice = await interface.ask_choice(
            "Allow reading file?",
            [
                "Read and send content and metadata",
                "Read and inspect content first",
                "Send metadata only",
                "Don't send anything",
            ],
        )

    if choice == 2:
        await interface.display_warning("Rejected")
        return ToolResult(content=metadata)

    if choice == 3:
        await interface.display_warning("Rejected")
        return ToolResult(content="User declined to send anything.")

    # choice in (0, 1): read and display the content before deciding further
    if line_ranges:
        try:
            content_ranges = await Filesystem.read_file_lines(
                abs_path, ranges=line_ranges
            )
        except ValueError as e:
            await interface.display_error(f"Invalid line range: {e}")
            return ToolResult(issues=[e])
        for start, end, text in content_ranges:
            await interface.display_text_box(
                text,
                title=f"Content: {abs_path} (lines {start} to {end})",
                language=abs_path.suffix,
            )
        content_str = "\n".join(text for _, _, text in content_ranges)
    else:
        read_result = await Filesystem.read_file(abs_path)
        content_str = (
            read_result.content
            if read_result.encoding == "text"
            else "(binary content)"
        )
        await interface.display_text_box(
            content_str,
            title=f"Content: {abs_path}",
            language=abs_path.suffix,
            collapsed=choice == 0,
        )

    if choice == 0:
        await interface.display_success("Accepted")
        return ToolResult(content=content_str)

    # choice == 1: inspect first, then decide
    send_choice = await interface.ask_choice(
        "Send file content?",
        ["Send content and metadata", "Send metadata only", "Don't send anything"],
    )
    if send_choice == 0:
        await interface.display_success("Accepted")
        return ToolResult(content=content_str)
    if send_choice == 1:
        await interface.display_warning("Rejected")
        return ToolResult(content=metadata)
    await interface.display_warning("Rejected")
    return ToolResult(content="User declined to send anything.")


async def read(
    ctx: SolveigContext,
    path: str,
    metadata_only: bool,
    line_ranges: list[list[int]] | None = None,
) -> ToolResult:
    """Read a file or directory.

    Files can be read for metadata only, full contents, or specific line ranges.

    Args:
        path: File or directory path to read (supports ~ for home directory).
        metadata_only: If true, read only file/directory metadata; otherwise also read file content.
        line_ranges: Optional line ranges to read, e.g. [[10, 50], [100, -1]]. If provided, only
            these ranges are read (up to 3 ranges, 1-indexed, inclusive). Use end=-1 to read to end
            of file, e.g. [[10, -1]]. If not provided, reads the entire file. Ignored for
            directories and metadata_only.
    """
    config, interface = ctx.deps.config, ctx.deps.interface
    path = validate_non_empty_path(path)
    if line_ranges:
        _validate_line_ranges(line_ranges)

    abs_path = Filesystem.get_absolute_path(path)

    async with interface.with_group(
        f"Read: {path}", auto_collapse=config.auto_collapse_tools
    ):
        if Filesystem.path_matches_patterns(abs_path, config.ignore_paths):
            await interface.display_error(f"Path blocked by ignore_paths: {abs_path}")
            return ToolResult(issues=[f"path blocked by ignore_paths: {abs_path}"])

        try:
            await Filesystem.validate_read_access(abs_path)
        except (FileNotFoundError, PermissionError, IsADirectoryError) as e:
            await interface.display_error(f"Cannot access {abs_path}: {e}")
            return ToolResult(issues=[e])

        path_matches = Filesystem.path_matches_patterns(
            abs_path, config.auto_allowed_paths
        )
        metadata = await Filesystem.read_metadata(abs_path)

        await interface.display_text(str(abs_path), prefix="Path:")

        if metadata.is_directory or metadata_only:
            return await _read_metadata_only(interface, path_matches, metadata)

        return await _read_content(
            interface, abs_path, path_matches, line_ranges, metadata
        )
