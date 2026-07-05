from __future__ import annotations

from solveig.schema.base import BaseSolveigModel


class WriteResult(BaseSolveigModel):
    """Structured metadata for an accepted `write` call - not sent to the LLM."""

    accepted: bool
    path: str
