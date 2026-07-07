"""Core tool functions the LLM can call, registered on a pydantic-ai FunctionToolset."""

from .core.command import command
from .core.copy import copy
from .core.delete import delete
from .core.edit import edit
from .core.http import http
from .core.move import move
from .core.read import read
from .core.task import update_tasks
from .core.write import write
from .result import ToolResult

CORE_TOOLS = [
    read,
    write,
    edit,
    delete,
    copy,
    move,
    command,
    http,
    update_tasks,
]

__all__ = [
    "CORE_TOOLS",
    "ToolResult",
    "read",
    "write",
    "edit",
    "delete",
    "copy",
    "move",
    "command",
    "http",
    "update_tasks",
]
