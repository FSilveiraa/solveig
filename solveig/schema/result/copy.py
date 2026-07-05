from __future__ import annotations

from solveig.schema.base import BaseSolveigModel


class CopyResult(BaseSolveigModel):
    """Structured metadata for an accepted `copy` call - not sent to the LLM."""

    accepted: bool
    source_path: str
    destination_path: str
