from __future__ import annotations

from typing import Literal

from ...utils.file import Metadata
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
