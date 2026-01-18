from __future__ import annotations

from typing import Literal

from .base import ToolResult


class EditResult(ToolResult):
    """Result of an edit operation."""

    title: Literal["edit"] = "edit"
    path: str

    # Replacement statistics
    occurrences_found: int | None = None
    occurrences_replaced: int | None = None
