"""Registry for dynamically discovered plugin tools.

Unlike core tools (hand-listed in `CORE_TOOLS`, no marker needed), plugin tools
are found by scanning `solveig.plugins.library` at runtime (`discover_plugins`),
so there's no static list anyone edits by hand. `@tool` is that missing piece: a
plugin author's only job is to decorate their tool so it self-registers into
`PLUGIN_TOOLS` — and, if it declared trigger names, into the plugin subcommand
store at the same moment.

`PLUGIN_TOOLS` mirrors `CORE_TOOLS`'s shape: a plain list. Its elements are
`BaseTool` subclasses (typed config via `settings()`, like core) OR
`FunctionTool` wrappers around plain callables — both kinds carry a DECLARED
`config_model`, so schema compose reads `entry.config_model` directly (no
getattr fallback, no stash). `plugin_tool_name` derives the dispatch name on
demand (`tool_name()`/`__name__`) — no separate index.
"""

import warnings
from collections.abc import Callable
from typing import Any, overload

from solveig.subcommands.base import PLUGIN_SUBCOMMANDS, SUBCOMMANDS
from solveig.tools.base import BaseTool, tool_from_callable
from solveig.tools.config import ToolConfig
from solveig.tools.orchestration import tool_subcommand

#: Discovered plugin tools, populated by `@tool` self-registration during
#: discovery. Every element is a tool CLASS: a `BaseTool` subclass as declared, or
#: the class `tool_from_callable` builds from a plain callable - so nothing
#: downstream sees a second kind of thing.
PLUGIN_TOOLS: list[type[BaseTool]] = []


@overload
def tool(entry: type[BaseTool]) -> type[BaseTool]: ...
@overload
def tool(entry: Callable[..., Any]) -> type[BaseTool]: ...
@overload
def tool(
    *, config_model: type[ToolConfig]
) -> Callable[[Callable[..., Any]], type[BaseTool]]: ...
def tool(entry=None, *, config_model=None):
    """Register a plugin tool into `PLUGIN_TOOLS`. Usable bare (`@tool`) or with a
    config type (`@tool(config_model=MyConfig)`).

    A `BaseTool` subclass already carries its own `config_model` and registers as
    it is. A plain callable is built into a tool class by `tool_from_callable`,
    which also owns which config type a callable gets when none is named here."""

    def register(tool: type[BaseTool] | Callable[..., Any]) -> type[BaseTool]:
        # `BaseTool` subclasses are callable too, so the class check comes first:
        #  only something that isn't already a tool gets built into one.
        if not (isinstance(tool, type) and issubclass(tool, BaseTool)):
            tool = (
                tool_from_callable(tool)
                if config_model is None
                else tool_from_callable(tool, config_model)
            )

        PLUGIN_TOOLS.append(tool)
        # A tool's `/command` is built and stored the moment the tool is
        # declared, through the same entrypoint the core tool list uses. The
        # plugin store is emptied before each rescan, so re-declaring on reload
        # replaces rather than duplicates.
        if (subcommands := tool_subcommand(tool)) is not None:
            for refused in SUBCOMMANDS.add(PLUGIN_SUBCOMMANDS, subcommands):
                warnings.warn(refused, stacklevel=2)
        return tool

    return register(entry) if entry is not None else register


def clear_tools() -> None:
    PLUGIN_TOOLS.clear()


__all__ = [
    "PLUGIN_TOOLS",
    "tool",
    "clear_tools",
]
