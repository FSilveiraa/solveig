"""Core tool functions the LLM can call, registered on a pydantic-ai FunctionToolset."""

from .command import command
from .contract import ToolResult, tool
from .copy import copy
from .delete import delete
from .edit import edit
from .http import http
from .move import move
from .read import read
from .task import update_tasks
from .write import write

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
    "tool",
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
