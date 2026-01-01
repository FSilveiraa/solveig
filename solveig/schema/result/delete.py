from __future__ import annotations

from typing import Literal

from .base import ToolResult


class DeleteResult(ToolResult):
    title: Literal["delete"] = "delete"
    path: str
