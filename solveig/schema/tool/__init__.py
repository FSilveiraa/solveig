"""Core tool functions the LLM can call, registered on a pydantic-ai FunctionToolset.

Migration in progress - see ignore/project-logs/2026-07-04-18-34-pydantic-ai-migration.md.
Old BaseTool-model implementations moved to ignore/pre-pydantic-ai-schema/ for reference.
"""

from .command import command
from .copy import copy
from .delete import delete
from .edit import edit
from .http import http
from .move import move
from .read import read
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
]

__all__ = [
    "CORE_TOOLS",
    "read",
    "write",
    "edit",
    "delete",
    "copy",
    "move",
    "command",
    "http",
]
