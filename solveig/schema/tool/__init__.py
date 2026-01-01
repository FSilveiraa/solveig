"""Tools module - core request types that LLMs can make."""

from .base import BaseTool
from .command import CommandTool
from .copy import CopyTool
from .delete import DeleteTool
from .move import MoveTool
from .read import ReadTool
from .write import WriteTool

CORE_TOOLS: list[type[BaseTool]] = [
    CommandTool,
    CopyTool,
    DeleteTool,
    MoveTool,
    ReadTool,
    WriteTool,
]

# Rebuild Pydantic models to resolve forward references
for tool in CORE_TOOLS:
    tool.model_rebuild()

__all__ = [
    "CORE_TOOLS",
    "BaseTool",
    "ReadTool",
    "WriteTool",
    "CommandTool",
    "MoveTool",
    "CopyTool",
    "DeleteTool",
]
