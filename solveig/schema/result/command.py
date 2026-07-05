from __future__ import annotations

from solveig.schema.base import BaseSolveigModel


class CommandResult(BaseSolveigModel):
    """Structured metadata for an accepted `command` call - not sent to the LLM."""

    accepted: bool
    command: str
    stdout: str | None = None
    stderr: str | None = None
