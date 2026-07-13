"""Core tools the LLM can call, registered on a pydantic-ai FunctionToolset.

Migration in progress (Phase 5): tools are moving from plain `(ctx, *args)`
functions back to declarative `BaseTool` subclasses. `CORE_TOOLS` holds a mix
of both during the conversion - `AvailableTools.rebuild()` calls `.as_tool()`
on any `BaseTool` subclass and takes the plain functions as-is.
"""

from .base import BaseTool
from .core.command import command
from .core.copy import copy
from .core.delete import delete
from .core.edit import EditTool
from .core.http import http
from .core.move import move
from .core.read import read
from .core.task import update_tasks
from .core.write import write
from .result import ToolResult

CORE_TOOLS = [
    read,
    write,
    EditTool,
    delete,
    copy,
    move,
    command,
    http,
    update_tasks,
]

__all__ = [
    "CORE_TOOLS",
    "BaseTool",
    "ToolResult",
    "read",
    "write",
    "EditTool",
    "delete",
    "copy",
    "move",
    "command",
    "http",
    "update_tasks",
]
