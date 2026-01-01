from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

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
