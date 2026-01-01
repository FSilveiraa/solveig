from __future__ import annotations

from typing import Literal

from .base import ToolResult


class WriteResult(ToolResult):
    title: Literal["write"] = "write"
    path: str
