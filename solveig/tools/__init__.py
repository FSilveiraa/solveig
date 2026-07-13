"""Core tools the LLM can call, registered on a pydantic-ai FunctionToolset.

All 9 core tools are declarative `BaseTool` subclasses (Phase 5) - see
`solveig/tools/base.py`. `AvailableTools.rebuild()` calls `.as_tool()` on each
to build the pydantic-ai-facing callable.
"""

from .base import BaseTool
from .core.command import CommandTool
from .core.copy import CopyTool
from .core.delete import DeleteTool
from .core.edit import EditTool
from .core.http import HttpTool
from .core.move import MoveTool
from .core.read import ReadTool
from .core.task import TasksTool
from .core.write import WriteTool
from .result import ToolResult

CORE_TOOLS: list[type[BaseTool]] = [
    ReadTool,
    WriteTool,
    EditTool,
    DeleteTool,
    CopyTool,
    MoveTool,
    CommandTool,
    HttpTool,
    TasksTool,
]

__all__ = [
    "CORE_TOOLS",
    "BaseTool",
    "ToolResult",
    "ReadTool",
    "WriteTool",
    "EditTool",
    "DeleteTool",
    "CopyTool",
    "MoveTool",
    "CommandTool",
    "HttpTool",
    "TasksTool",
]
