from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from solveig.interface import SolveigInterface

from .base import ToolResult


class EditResult(ToolResult):
    """Result of an edit operation."""

    title: Literal["edit"] = "edit"
    path: str

    # Replacement statistics
    occurrences_found: int | None = None
    occurrences_replaced: int | None = None

    async def _display_content(self, interface: SolveigInterface) -> None:
        if self.occurrences_replaced is not None:
            await interface.display_text(
                f"{self.occurrences_replaced} occurrence(s) replaced"
            )
