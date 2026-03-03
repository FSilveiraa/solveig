from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from solveig.interface import SolveigInterface

from .base import ToolResult


class CommandResult(ToolResult):
    title: Literal["command"] = "command"
    command: str
    success: bool | None = None
    stdout: str | None = None

    async def _display_content(self, interface: SolveigInterface) -> None:
        if self.stdout:
            await interface.display_text_block(self.stdout.rstrip(), title="Output")
