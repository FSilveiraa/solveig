"""Read tool - allows LLM to read files and directories."""

from typing import Literal

from pydantic import Field, field_validator

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.result import ReadResult
from solveig.utils.file import Filesystem, Metadata

from .base import BaseTool, validate_non_empty_path


class ReadTool(BaseTool):
    title: Literal["read"] = "read"
    path: str = Field(
        ...,
        description="File or directory path to read (supports ~ for home directory)",
    )
    metadata_only: bool = Field(
        ...,
        description="If true read only file/directory metadata, otherwise also read file content",
    )
    line_ranges: list[list[int]] | None = Field(
        None,
        description="Optional line ranges to read, e.g., [[10, 50], [100, -1]]. "
        "If provided, only these ranges are read (up to 3 ranges, 1-indexed, inclusive). "
        "Use end=-1 to read to end of file, e.g., [[10, -1]]."
        "If not provided, reads the entire file. Ignored for directories and metadata_only.",
    )

    @field_validator("path")
    @classmethod
    def path_not_empty(cls, path: str) -> str:
        return validate_non_empty_path(path)

    @field_validator("line_ranges")
    @classmethod
    def validate_line_ranges(
        cls, ranges: list[list[int]] | None
    ) -> list[tuple[int, int]] | None:
        if ranges is None:
            return None

        if len(ranges) > 3:
            raise ValueError("Maximum 3 line ranges allowed")

        result: list[tuple[int, int]] = []
        for i, range_list in enumerate(ranges):
            if len(range_list) != 2:
                raise ValueError(
                    f"Range {i + 1}: Must have exactly 2 elements [start, end]"
                )
            start, end = range_list
            if start < 1:
                raise ValueError(f"Range {i + 1}: Start line must be >= 1")
            # end can be -1 (meaning "end of file") or >= start
            if end != -1 and end < start:
                raise ValueError(f"Range {i + 1}: End line must be >= start line or -1")
            result.append((start, end))

        return result

    async def display_header(self, interface: "SolveigInterface") -> None:
        """Display read tool header."""
        await super().display_header(interface)
        await interface.display_file_info(source_path=self.path)

        metadata = await Filesystem.read_metadata(
            Filesystem.get_absolute_path(self.path)
        )

        # Display the dir listing for directories (1-depth tree)
        if metadata.is_directory:
            await interface.display_tree(metadata=metadata)
        # The metadata vs content distinction only makes sense for files
        else:
            if self.metadata_only:
                request_desc = "metadata"
            elif self.line_ranges:
                ranges_str = ", ".join(
                    f"[{start} to {end}]" for start, end in self.line_ranges
                )
                request_desc = f"lines {ranges_str} and metadata"
            else:
                request_desc = "content and metadata"
            await interface.display_text(request_desc, prefix="Requesting:")

    def create_error_result(self, error_message: str, accepted: bool) -> "ReadResult":
        """Create ReadResult with error."""
        return ReadResult(
            tool=self,
            path=str(Filesystem.get_absolute_path(self.path)),
            accepted=accepted,
            error=error_message,
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of read capability."""
        return (
            "read(comment, path, metadata_only, line_ranges=null): reads a file or directory. "
            "Files can be read for metadata only, full contents or specific line ranges."
        )

    async def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "ReadResult":
        abs_path = Filesystem.get_absolute_path(self.path)

        try:
            await Filesystem.validate_read_access(abs_path)
        except (FileNotFoundError, PermissionError, IsADirectoryError) as e:
            await interface.display_error(f"Cannot access {str(abs_path)}: {e}")
            return self.create_error_result(str(e), accepted=False)

        path_matches = Filesystem.path_matches_patterns(
            abs_path, config.auto_allowed_paths
        )

        metadata: Metadata | None = await Filesystem.read_metadata(abs_path)
        assert metadata is not None

        # Case 1: Directories or metadata-only requests
        if metadata.is_directory or self.metadata_only:
            send_metadata = False
            if path_matches:
                await interface.display_info(
                    "Sending metadata since path is auto-allowed."
                )
                send_metadata = True
            else:
                send_metadata = (
                    await interface.ask_choice(
                        "Send metadata to assistant?", ["Yes", "No"]
                    )
                    == 0
                )

            return ReadResult(
                tool=self,
                metadata=metadata if send_metadata else None,
                path=str(abs_path),
                accepted=send_metadata,
            )

        # Case 2: File content requests
        else:
            accepted = False
            content: list[tuple[int, int, str]] | None = None

            if path_matches:
                await interface.display_info(
                    "Reading and sending file since path is auto-allowed."
                )
                choice = 0  # Corresponds to "Read and send"
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

            if choice in {0, 1}:
                # Branch based on whether line ranges are requested
                if self.line_ranges:
                    # Use read_file_lines for specific ranges
                    try:
                        content = await Filesystem.read_file_lines(
                            abs_path, ranges=self.line_ranges
                        )
                    except ValueError as e:
                        await interface.display_error(f"Invalid line range: {e}")
                        return self.create_error_result(str(e), accepted=False)

                    metadata.encoding = "text"

                    # Display each range in its own block
                    for start, end, text in content:
                        await interface.display_text_block(
                            text,
                            title=f"Content: {abs_path} (lines {start} to {end})",
                            language=abs_path.suffix,
                        )
                else:
                    # Use read_file for full file (handles binary too)
                    read_result = await Filesystem.read_file(abs_path)
                    metadata.encoding = read_result.encoding

                    # Convert to content format: [(start, end, content)]
                    if read_result.encoding == "text":
                        line_count = read_result.content.count("\n") + 1
                        content = [(1, line_count, read_result.content)]
                    else:
                        # Binary file - use (0, 0) to indicate whole binary file
                        content = [(0, 0, read_result.content)]

                    await interface.display_text_block(
                        read_result.content
                        if read_result.encoding == "text"
                        else "(binary content)",
                        title=f"Content: {abs_path}",
                        language=abs_path.suffix,
                    )

                # 0: Read and send
                if choice == 0:
                    accepted = True
                # 1: Read and inspect
                elif choice == 1:
                    try:
                        send_choice = await interface.ask_choice(
                            "Send file content?",
                            [
                                "Send content and metadata",
                                "Send metadata only",
                                "Don't send anything",
                            ],
                        )
                        if send_choice == 0:
                            accepted = True
                        elif send_choice == 1:
                            accepted = False  # Didn't get content
                            content = None
                        else:  # Don't send anything
                            accepted = False
                            content = None
                            metadata = None

                    except (PermissionError, OSError, UnicodeDecodeError) as e:
                        await interface.display_error(
                            f"Failed to read file content: {e}"
                        )
                        return self.create_error_result(str(e), accepted=False)
            # 2: Send metadata only
            elif choice == 2:
                accepted = False  # Didn't get content
                content = None
            # 3: Don't send anything
            else:
                accepted = False
                content = None
                metadata = None

            return ReadResult(
                tool=self,
                metadata=metadata,
                content=content,
                path=str(abs_path),
                accepted=accepted,
            )
