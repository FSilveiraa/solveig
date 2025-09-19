from __future__ import annotations

from pathlib import PurePath

from .base import RequirementResult


class MoveResult(RequirementResult):
    source_path: str | PurePath
    destination_path: str | PurePath
