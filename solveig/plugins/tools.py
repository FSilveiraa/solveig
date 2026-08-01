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
from collections.abc import Awaitable, Callable
from typing import Any, cast, overload

from solveig.subcommands.base import PLUGIN_SUBCOMMANDS, SUBCOMMANDS
from solveig.tools.base import BaseTool, ToolConfig
from solveig.tools.orchestration import tool_subcommand


class FunctionTool:
    """A plain callable plugin tool as a callable object — the parallel of a
    `BaseTool` subclass for the function case. `config_model` is DECLARED on
    the wrapper (default bare ToolConfig = enabled-only), so schema compose
    reads it the same way for both kinds of plugin tool."""

    def __init__(
        self,
        fn: Callable[..., Awaitable[object]],
        config_model: type[ToolConfig] = ToolConfig,
    ):
        self.fn = fn
        self.config_model = config_model
        self.__name__ = fn.__name__
        self.__module__ = fn.__module__

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.fn(*args, **kwargs)


# A plugin tool as registered: a BaseTool subclass, a plain callable (pre-
# wrap, only ever seen at the `@tool` boundary), or a FunctionTool (post-wrap —
# what PLUGIN_TOOLS actually holds for the callable case).
type PluginTool = Callable[..., Awaitable[object]] | type[BaseTool] | FunctionTool

# Discovered plugin tools, populated by `@tool` self-registration during discovery.
PLUGIN_TOOLS: list[PluginTool] = []


@overload
def tool(entry: PluginTool) -> PluginTool: ...
@overload
def tool(*, config_model: type[ToolConfig]) -> Callable[[PluginTool], PluginTool]: ...
def tool(entry=None, *, config_model=None):
    """Register a plugin tool into `PLUGIN_TOOLS`. Usable bare (`@tool`) or with a
    config type (`@tool(config_model=MyConfig)`).

    A `BaseTool[SomeConfig]` subclass already has its `config_model` auto-derived
    from the generic (and typed `self.settings(config)`), so it registers as-is;
    a plain callable is wrapped in `FunctionTool` so its config type is declared
    on the wrapper rather than stashed. Without `config_model=` a callable gets
    bare `ToolConfig` (enabled-only) and reads its config Any-style via
    `ctx.deps.config`."""

    def register(e: PluginTool) -> PluginTool:
        if isinstance(e, type) and issubclass(e, BaseTool):
            pass  # BaseTool: config_model auto-derived from the generic
        elif isinstance(e, FunctionTool):
            if config_model is not None:
                e.config_model = config_model
        elif callable(e):
            e = FunctionTool(
                cast(Callable[..., Awaitable[object]], e), config_model or ToolConfig
            )
        PLUGIN_TOOLS.append(e)
        # A tool's `/command` is built and stored the moment the tool is
        # declared, through the same entrypoint the core tool list uses. The
        # plugin store is emptied before each rescan, so re-declaring on reload
        # replaces rather than duplicates.
        sub = tool_subcommand(e)
        if sub is not None:
            for refused in SUBCOMMANDS.add(PLUGIN_SUBCOMMANDS, sub):
                warnings.warn(refused, stacklevel=2)
        return e

    return register(entry) if entry is not None else register


def clear_tools() -> None:
    PLUGIN_TOOLS.clear()


def plugin_tool_name(entry: PluginTool) -> str:
    """The name a call dispatches under: `.tool_name()` for a `BaseTool`
    subclass (e.g. `TreeTool` -> `"tree"`), `__name__` for a FunctionTool."""
    if isinstance(entry, type) and issubclass(entry, BaseTool):
        return entry.tool_name()
    return entry.__name__


def config_model_of(entry: PluginTool) -> type[ToolConfig]:
    """The tool's config type for schema composition — declared on both kinds
    (a BaseTool ClassVar auto-derived from the generic, a FunctionTool field),
    so compose reads it uniformly."""
    if isinstance(entry, type) and issubclass(entry, BaseTool):
        return entry.config_model
    if isinstance(entry, FunctionTool):
        return entry.config_model
    # Bare callable that was never wrapped (registered without @tool's factory).
    return ToolConfig


__all__ = [
    "PLUGIN_TOOLS",
    "PluginTool",
    "FunctionTool",
    "tool",
    "clear_tools",
    "plugin_tool_name",
    "config_model_of",
]
