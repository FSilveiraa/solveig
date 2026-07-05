from __future__ import annotations

from solveig.schema.base import BaseSolveigModel

from ...utils.file import Metadata


class ReadResult(BaseSolveigModel):
    """Structured metadata for an accepted `read` call - not sent to the LLM.

    Carried via `pydantic_ai.messages.ToolReturn.metadata`, for hooks and (later)
    session-replay display. The LLM only ever sees the tool's plain `str` return value.
    """

    accepted: bool
    # The requested path can be different from the canonical one in metadata
    path: str
    metadata: Metadata | None = None
    # Content is a list of (start_line, end_line, content_string) tuples
    # When reading full file: [(1, total_lines, full_content)]
    # When reading ranges: [(start1, end1, content1), (start2, end2, content2), ...]
    content: list[tuple[int, int, str]] | None = None
