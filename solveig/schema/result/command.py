from __future__ import annotations

from typing import Literal

from .base import ToolResult


class CommandResult(ToolResult):
    title: Literal["command"] = "command"
    command: str
    success: bool | None = None
    stdout: str | None = None
