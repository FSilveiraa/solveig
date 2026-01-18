"""
Schema definitions for Solveig's structured communication with LLMs.

This module defines the data structures used for:
- Messages exchanged between user, LLM, and system
- Tools (file operations, shell commands)
- Results and error handling
"""

from .result import (  # noqa: F401
    CommandResult,
    CopyResult,
    DeleteResult,
    EditResult,
    MoveResult,
    ReadResult,
    ToolResult,
    WriteResult,
)
from .tool import (  # noqa: F401
    BaseTool,
    CommandTool,
    CopyTool,
    DeleteTool,
    EditTool,
    MoveTool,
    ReadTool,
    WriteTool,
)

CORE_TOOLS: list[type[BaseTool]] = [
    CommandTool,
    CopyTool,
    DeleteTool,
    EditTool,
    MoveTool,
    ReadTool,
    WriteTool,
]

CORE_RESULTS: list[type[ToolResult]] = [
    ReadResult,
    WriteResult,
    EditResult,
    CommandResult,
    MoveResult,
    CopyResult,
    DeleteResult,
    ToolResult,
]


# Rebuild Pydantic models to resolve forward references
# Order matters: tools first, then results that reference them
for tool in CORE_TOOLS:
    tool.model_rebuild()

for result in CORE_RESULTS:
    result.model_rebuild()


__all__ = ["CORE_TOOLS", "BaseTool"]
