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

from config.section.static import ConfigSection
from solveig.subcommands.base import CORE_TOOL_SUBCOMMANDS, SUBCOMMANDS
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
from ..config import FileToolConfig, ToolConfig


# A tool may be named `copy`, and a field with that name necessarily shadows
# pydantic's deprecated v1 `BaseModel.copy()` — pydantic warns about the shadow
# with no way to opt out (its check in `_internal/_fields.py` has no config
# switch). The shadow is inert here: nothing calls `.copy()` on THIS section
# (the one `.copy()` left in the tree is on a tool's own config, and even that
# call discards its result), the code uses `model_copy`, and this section's own
# verbs are path-based. `delete` was fixed properly — the verb is now `unset` —
# so this filter is anchored on the exact message instead of quieting the class
# wholesale: a new shadowing name would still be reported. The filter is
# process-wide from this import onward, which is why the message names the class.
warnings.filterwarnings(
    "ignore",
    message=r'Field name "copy" in "CoreToolsConfig" shadows an attribute in parent',
    category=UserWarning,
)


class CoreToolsConfig(ConfigSection):
    read: FileToolConfig[ReadTool] = Field(default_factory=FileToolConfig[ReadTool])
    write: FileToolConfig[WriteTool] = Field(default_factory=FileToolConfig[WriteTool])
    edit: FileToolConfig[EditTool] = Field(default_factory=FileToolConfig[EditTool])
    delete: FileToolConfig[DeleteTool] = Field(default_factory=FileToolConfig[DeleteTool])
    copy: FileToolConfig[CopyTool] = Field(default_factory=FileToolConfig[CopyTool])
    move: FileToolConfig[MoveTool] = Field(default_factory=FileToolConfig[MoveTool])
    command: CommandConfig[CommandTool] = Field(default_factory=CommandConfig[CommandTool])
    http: HttpConfig[HttpTool] = Field(default_factory=HttpConfig[HttpTool])
    todo: ToolConfig[TodoTool] = Field(default_factory=ToolConfig[TodoTool])


# TODO: move this to some class validator or something
# TODO: there should be a cleaner way to `walk` a config's fields,
#  especially for dynamic sections where it's structurally implied
#  their entries are kv mappings. However this is schema, not instance.
for field in CoreToolsConfig.model_fields.values():
    if (subcommand := tool_subcommand(field.annotation.tool_class)) is not None:
        for _refused in SUBCOMMANDS.add(CORE_TOOL_SUBCOMMANDS, subcommand):
            warnings.warn(_refused, stacklevel=2)

__all__ = [
    "CoreToolsConfig",
]
