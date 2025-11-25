from __future__ import annotations

from typing import Literal

from .base import RequirementResult


class MoveResult(RequirementResult):
    title: Literal["move"] = "move"
    source_path: str
    destination_path: str
