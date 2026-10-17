"""Plugin tool declaration.

Exposes an `@tool` decorator that accepts both BaseTool subclasses and
plain callables. The decorator only DECLARES — it builds the tool class and
records `(name, config_model, module)` for the scan that imported this module,
which is what types the `plugins.tools` entry after the imports. It never
touches the config: an import cannot await the observers a write would reach,
and the scan types once per plugin instead of once per decorator."""

from collections.abc import Callable
from typing import Any, overload

from solveig.plugins.scan import declare
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
    """Declare a plugin tool. Usable bare (`@tool`) or with a config type
    (`@tool(config_model=MyConfig)`).

    A `BaseTool` subclass already carries its own `config_model` and declares
    as it is. A plain callable is built into a tool class by
    `tool_from_callable`, which also owns which config type a callable gets
    when none is named here. The `plugins.tools` entry itself is typed by the
    scan, after every plugin module has been imported."""

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

        # The recording raises `RuntimeError` when no scan is running — there
        #  would be no scan to type the entry with.
        declare(tool_class.tool_name(), tool_class.config_model, tool_class.__module__)
        return tool_class

    return register(entry) if entry is not None else register


__all__ = [
    "tool",
]
