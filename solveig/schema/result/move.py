from __future__ import annotations

from typing import Literal

from .base import ToolResult


class MoveResult(ToolResult):
    title: Literal["move"] = "move"
    source_path: str
    destination_path: str
