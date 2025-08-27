from __future__ import annotations

from .base import RequirementResult


class CommandResult(RequirementResult):
    command: str
    success: bool | None = None
    stdout: str | None = None
