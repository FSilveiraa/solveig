"""Registry for dynamically discovered plugin tools.

Unlike core tools (hand-listed in `CORE_TOOLS`, no marker needed), plugin tools
are found by scanning modules at runtime (`load_and_filter_plugin_tools`), so
there's no static list anyone edits by hand. `@tool` is that missing piece: a
plugin author's only job is to decorate their tool so it self-registers into
`PLUGIN_TOOLS` — pure bookkeeping, no signature rewriting.

`PLUGIN_TOOLS` mirrors `CORE_TOOLS`'s shape: a plain list. Its elements are
`BaseTool` subclasses (typed config via `settings()`, like core) OR
`FunctionTool` wrappers around plain callables — both kinds carry a DECLARED
`config_model`, so schema compose reads `entry.config_model` directly (no
getattr fallback, no stash). `plugin_tool_name` / `plugin_owner` derive
per-entry facts on demand (name from `tool_name()`/`__name__`, owner from the
module path) — no separate index.
"""

from collections.abc import Awaitable, Callable
from typing import Any, cast, overload

from solveig.plugins.utils import rescan_and_load_plugins
from solveig.tools.base import BaseTool, ToolConfig


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


def load_and_filter_plugin_tools() -> list[str]:
    """Discover plugin tool modules into `PLUGIN_TOOLS` — idempotent and UI-free.

    Returns discovery error messages for the caller to surface; reporting is a
    separate step, so discovery can run before the interface exists. Plugins
    register via `@tool` at import; enabled-by-default (gating is decided live
    at call time, so discovery has no use for config)."""
    clear_tools()
    _succeeded, _failed, errors = rescan_and_load_plugins("solveig.plugins.tools")
    return errors


__all__ = [
    "PLUGIN_TOOLS",
    "PluginTool",
    "FunctionTool",
    "tool",
    "clear_tools",
    "plugin_tool_name",
    "config_model_of",
    "load_and_filter_plugin_tools",
]
