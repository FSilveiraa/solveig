from __future__ import annotations

from solveig.schema.base import BaseSolveigModel


class EditResult(BaseSolveigModel):
    """Structured metadata for an accepted `edit` call - not sent to the LLM."""

    accepted: bool
    path: str

    # Replacement statistics
    occurrences_found: int | None = None
    occurrences_replaced: int | None = None
