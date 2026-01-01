from __future__ import annotations

from typing import Literal

from .base import ToolResult


class CopyResult(ToolResult):
    title: Literal["copy"] = "copy"
    source_path: str
    destination_path: str
