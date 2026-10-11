"""
Registry for dynamically discovered plugin tools.

Exposes an `@tool` decorator that accepts both BaseTool subclasses and
plain callables.

PLUGIN_TOOLS is the current list of known plugin tools.
"""

from collections.abc import Callable
from typing import Any, overload

from solveig.tools.base import BaseTool, tool_from_callable
from solveig.tools.config import ToolConfig

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
        # Tools are callables, so check if it's a plain method by checking
        #  if it's not a tool
        # TODO: this check happens elsewhere, review why several places need it
        if not (isinstance(tool, type) and issubclass(tool, BaseTool)):
            tool = (
                tool_from_callable(tool)
                if config_model is None
                else tool_from_callable(tool, config_model)
            )

        PLUGIN_TOOLS.append(tool)
        return tool

    return register(entry) if entry is not None else register


def clear_tools() -> None:
    PLUGIN_TOOLS.clear()


__all__ = [
    "PLUGIN_TOOLS",
    "tool",
    "clear_tools",
]
