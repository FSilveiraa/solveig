"""Registry for dynamically discovered plugin tools.

Unlike core tools (hand-listed in `CORE_TOOLS`, no marker needed), plugin tools
are found by scanning modules at runtime (`load_and_filter_plugin_tools`), so
there's no static list anyone edits by hand. `@tool` is that missing piece: a
plugin author's only job is to decorate their tool so it self-registers into
`PLUGIN_TOOLS` — pure bookkeeping, no signature rewriting.

`PLUGIN_TOOLS` mirrors `CORE_TOOLS`'s shape: a plain list. Its elements are
`BaseTool` subclasses (typed config via `settings()`, like core) OR plain
callables. A callable gets bare `ToolConfig` (enabled-only) unless it declares
`@tool(config_model=MyConfig)`; either way it reads its config Any-style from
`config.plugins.tools.<name>` (a `BaseTool` reads it typed). `config_model_of` /
`plugin_tool_name` / `plugin_owner` derive per-entry facts on demand (name from
`tool_name()`/`__name__`, owner from the module path) — no separate index.
"""

from collections.abc import Awaitable, Callable
from typing import overload

from solveig.config import SolveigConfig
from solveig.plugins.utils import rescan_and_load_plugins
from solveig.tools.base import BaseTool, ToolConfig

type PluginTool = Callable[..., Awaitable[object]] | type[BaseTool]

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
    from the generic (and typed `self.settings(config)`), so it needs nothing here;
    `config_model=` is for a plain callable (which has no generic) that wants a
    typed `config.plugins.tools.<name>` schema — or to override the derived type on
    a class. Without it a callable gets bare `ToolConfig` (enabled-only) and reads
    its config Any-style via `ctx.deps.config`."""

    def register(e: PluginTool) -> PluginTool:
        if config_model is not None:
            # A plain callable has no declared `config_model`; stashing one is how
            # a function opts into a typed config (a BaseTool sets it as a ClassVar).
            e.config_model = config_model  # type: ignore[union-attr]
        PLUGIN_TOOLS.append(e)
        return e

    return register(entry) if entry is not None else register


def clear_tools() -> None:
    PLUGIN_TOOLS.clear()


def plugin_tool_name(entry: PluginTool) -> str:
    """The name a call dispatches under: `.tool_name()` for a `BaseTool` subclass
    (e.g. `TreeTool` -> `"tree"`), `__name__` for a plain callable."""
    if isinstance(entry, type) and issubclass(entry, BaseTool):
        return entry.tool_name()
    return entry.__name__


def config_model_of(entry: PluginTool) -> type[ToolConfig]:
    """The tool's config type for schema composition: its `config_model` (a
    `BaseTool` ClassVar, or a callable's `@tool(config_model=...)` stash) or bare
    `ToolConfig`. The one uniform accessor compose reads over both kinds."""
    return getattr(entry, "config_model", ToolConfig)


def load_and_filter_plugin_tools(config: SolveigConfig) -> list[str]:
    """Discover plugin tool modules into `PLUGIN_TOOLS` — idempotent and UI-free.

    Returns discovery error messages for the caller to surface; reporting is a
    separate step (so discovery can run before the interface exists, for the
    two-phase config bootstrap). Plugins register via `@tool` at import;
    enabled-by-default (gating is decided live). `config` is kept on the signature
    for symmetry with the hook loader and future per-plugin gating."""
    clear_tools()
    _succeeded, _failed, errors = rescan_and_load_plugins("solveig.plugins.tools")
    return errors


__all__ = [
    "PLUGIN_TOOLS",
    "PluginTool",
    "tool",
    "clear_tools",
    "plugin_tool_name",
    "config_model_of",
    "load_and_filter_plugin_tools",
]
