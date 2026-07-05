from __future__ import annotations

from solveig.schema.base import BaseSolveigModel


class DeleteResult(BaseSolveigModel):
    """Structured metadata for an accepted `delete` call - not sent to the LLM."""

    accepted: bool
    path: str
