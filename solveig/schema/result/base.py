from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from solveig.interface import SolveigInterface

# Circular import fix:
# - This module (result/base.py) needs Tool classes for type hints
# - tool/base.py imports Result classes for actual usage
# - TYPE_CHECKING solves this: imports are only loaded during type checking,
#   not at runtime, breaking the circular dependency
if TYPE_CHECKING:
    from ..tool import BaseTool


class ToolResult(BaseModel):
    # we store the initial tool for debugging/error printing,
    # then when JSON'ing we usually keep a couple of its fields in the result's body
    # We keep paths separately from the tool, since we want to preserve both the path(s) the LLM provided
    # and their absolute value (~/Documents vs /home/jdoe/Documents)
    title: str
    tool: BaseTool = Field(exclude=True)
    accepted: bool
    error: str | None = None

    async def display(self, interface: SolveigInterface) -> None:
        async with interface.with_group(self.title.title()):
            await self.tool.display_header(interface)
            await self._display_content(interface)
            if self.error:
                await interface.display_error(self.error)
            else:
                if self.accepted:
                    await interface.display_success("Accepted")
                else:
                    await interface.display_warning("Rejected")
                # await interface.display_text("✓ Accepted" if self.accepted else "✗ Rejected")

    async def _display_content(self, interface: SolveigInterface) -> None:
        """Override in subclasses to show type-specific result content."""
        raise NotImplementedError()
