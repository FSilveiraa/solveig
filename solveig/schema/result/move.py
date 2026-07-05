from __future__ import annotations

from solveig.schema.base import BaseSolveigModel


class MoveResult(BaseSolveigModel):
    """Structured metadata for an accepted `move` call - not sent to the LLM."""

    accepted: bool
    source_path: str
    destination_path: str
