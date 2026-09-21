"""The core tool list, and the registration of the `/commands` it opts into.

The list stays hand-written rather than collected by a decorator: it is the one
place all nine can be read at a glance, and its ORDER is meaningful — it reaches
the model's tool schema and `/config list`. Their `/commands` are registered
right below it, through the entrypoint `@tool` uses for a plugin's, so both
kinds of tool contribute a command at the moment they are declared.

NOTE: this lives here rather than in `solveig/tools/__init__.py` — which is now
empty, and must stay empty. A package's `__init__` runs whenever ANY module
under it is imported, including `solveig.tools.base`; since `orchestration`
imports `plugins.hooks`, which imports `tools.base`, importing `orchestration`
up there would re-enter a half-initialized `plugins.hooks`. Down here nothing
triggers it but an explicit import of this module.
"""

import warnings

from pydantic import Field

from config import ConfigSection
from solveig.subcommands.base import CORE_TOOL_SUBCOMMANDS, SUBCOMMANDS
from solveig.tools.base import BaseTool
from solveig.tools.orchestration import tool_subcommand

from .command import CommandTool, CommandConfig
from .copy import CopyTool
from .delete import DeleteTool
from .edit import EditTool
from .http import HttpTool, HttpConfig
from .move import MoveTool
from .read import ReadTool
from .todo import TodoTool
from .write import WriteTool
from ..config import ToolConfig


# CORE_TOOLS: list[type[BaseTool]] = [
#     ReadTool,
#     WriteTool,
#     EditTool,
#     DeleteTool,
#     CopyTool,
#     MoveTool,
#     CommandTool,
#     HttpTool,
#     TodoTool,
# ]


# TODO: second source-of-truth for tool names
class CoreToolsConfig(ConfigSection):
    read: ToolConfig = Field(default_factory=ToolConfig)
    write: ToolConfig = Field(default_factory=ToolConfig)
    edit: ToolConfig = Field(default_factory=ToolConfig)
    delete: ToolConfig = Field(default_factory=ToolConfig)
    copy: ToolConfig = Field(default_factory=ToolConfig)
    move: ToolConfig = Field(default_factory=ToolConfig)
    command: CommandConfig = Field(default_factory=CommandConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    todo: ToolConfig = Field(default_factory=ToolConfig)


# TODO: move this to some class validator or something
for _tool in CORE_TOOLS:
    _sub = tool_subcommand(_tool)
    if _sub is not None:
        for _refused in SUBCOMMANDS.add(CORE_TOOL_SUBCOMMANDS, _sub):
            warnings.warn(_refused, stacklevel=2)

__all__ = [
    "CORE_TOOLS",
    "ReadTool",
    "WriteTool",
    "EditTool",
    "DeleteTool",
    "CopyTool",
    "MoveTool",
    "CommandTool",
    "HttpTool",
    "TodoTool",
]
