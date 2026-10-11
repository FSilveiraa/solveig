"""
Registry for dynamically discovered plugin tools.

Exposes an `@tool` decorator that accepts both BaseTool subclasses and
plain callables.

PLUGIN_TOOLS is the current list of known plugin tools.
"""

from collections.abc import Callable
from typing import Any, overload

from solveig.plugins.discovery import PLUGIN_TARGETS
from solveig.tools.base import BaseTool, tool_from_callable
from solveig.tools.config import ToolConfig




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

    def register(tool_class: type[BaseTool] | Callable[..., Any]) -> type[BaseTool]:
        # Tools are callables, so check if it's a plain method by checking
        #  if it's not a tool
        # TODO: this check happens elsewhere, review why several places need it
        if not (isinstance(tool_class, type) and issubclass(tool_class, BaseTool)):
            tool_class = (
                tool_from_callable(tool_class)
                if config_model is None
                else tool_from_callable(tool_class, config_model)
            )

        if (plugins_config := PLUGIN_TARGETS.get()) is None:
            # NOTE: this can't happen, and it's an example of why
            # PLUGIN_TARGETS may be a bad design
            raise RuntimeError(f"{tool_class.tool_name()!r} declared outside a plugin scan")
        else:
            # Type `my_tool: MyToolConfig` in the plugin tools config
            plugins_config.tools.set_type(tool_class.tool_name(), tool_class.config_model)
        return tool_class

    return register(entry) if entry is not None else register


__all__ = [
    "tool",
]
