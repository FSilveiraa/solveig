"""Core tool functions the LLM can call, registered on a pydantic-ai FunctionToolset.

Migration in progress - see ignore/project-logs/2026-07-04-18-34-pydantic-ai-migration.md.
Old BaseTool-model implementations moved to ignore/pre-pydantic-ai-schema/ for reference.
"""

from ..result import ToolResult
from ._decorator import tool
from .command import command
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
