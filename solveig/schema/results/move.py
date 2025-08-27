from __future__ import annotations

from pathlib import Path

from .base import RequirementResult


class MoveResult(RequirementResult):
    source_path: str | Path
    destination_path: str | Path
