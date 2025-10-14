from __future__ import annotations

from .base import RequirementResult


class MoveResult(RequirementResult):
    source_path: str
    destination_path: str
