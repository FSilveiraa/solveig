from __future__ import annotations

from typing import Literal

from solveig.interface import SolveigInterface

from ...utils.file import Metadata, Filesystem
from .base import ToolResult


class ReadResult(ToolResult):
    # The requested path can be different from the canonical one in metadata
    title: Literal["read"] = "read"
    path: str
    metadata: Metadata | None = None
    # Content is a list of (start_line, end_line, content_string) tuples
    # When reading full file: [(1, total_lines, full_content)]
    # When reading ranges: [(start1, end1, content1), (start2, end2, content2), ...]
    content: list[tuple[int, int, str]] | None = None

    async def _display_content(self, interface: SolveigInterface) -> None:
        if self.content:
            abs_path = Filesystem.get_absolute_path(self.metadata.path if self.metadata else self.path)

            if len(self.content) > 1:
                for start, end, text in self.content:
                    await interface.display_text_box(
                        text,
                        title=f"Content: {abs_path} (lines {start} to {end})",
                        language=abs_path.suffix,
                        collapsed=True,
                    )

            else:
                await interface.display_text_box(
                    text=self.content[0][2],
                    title=f"Content: {abs_path}",
                    language=abs_path.suffix,
                    collapsed=True,
                )