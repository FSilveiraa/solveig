"""Hook plugin registry - the `@before`/`@after` decorators and the state
they register into.

Lives here, in the plugins package, so a hook plugin author imports the
decorators from their own package (`from solveig.plugins.hooks import before,
after`, or `from solveig.plugins import before, after`) instead of reaching
into tools internals - mirroring `PLUGIN_TOOLS`/`tool` in
`plugins/tools/__init__.py`. The consumer on the tools side is
`build_tool_execution_capability()` (`solveig/tools/available.py`): it reads
`BEFORE_HOOKS`/`AFTER_HOOKS` at call time to run the registered hooks around a
tool call via pydantic-ai's native tool-execute hook points, but doesn't own
the registry - the same relationship `AvailableTools.rebuild()` already has
with `PLUGIN_TOOLS`.

Keyed by the *tool being hooked* (name or function), appended to a list -
unlike `PLUGIN_TOOLS.all`, a collision here isn't possible, since nothing is
indexed by a single plugin/file-derived key. Plugin name is only derived
(from the hook function's module path) on demand, for load reporting (and
Sub-project B's per-hook config).
"""

import warnings
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.plugins.utils import rescan_and_load_plugins
from solveig.tools.base import BaseTool, ToolConfig
from solveig.tools.result import ToolResult

BeforeHook = Callable[
    [dict[str, Any], SolveigConfig, SolveigInterface], Awaitable[None]
]
AfterHook = Callable[
    [ToolResult, SolveigConfig, SolveigInterface], Awaitable[ToolResult]
]

BEFORE_HOOKS: dict[str, list[BeforeHook]] = defaultdict(list)
AFTER_HOOKS: dict[str, list[AfterHook]] = defaultdict(list)


def _tool_key(target: "str | type[BaseTool] | Callable[..., Any]") -> str:
    """The registry key for a hook target: the actual tool name a call is
    dispatched under (`call.tool_name`), not a Python identifier. A `BaseTool`
    subclass keys by `.tool_name()` (e.g. `CommandTool` -> `"command"`); a
    plain tool function (not-yet-converted plugin tools) keys by `__name__`,
    same as the string it's registered under."""
    if isinstance(target, str):
        return target
    if isinstance(target, type) and issubclass(target, BaseTool):
        return target.tool_name()
    return target.__name__


def plugin_name(fn: Callable[..., Any]) -> str:
    """Derive a hook's owning plugin name from its module path (e.g. `solveig.plugins.hooks.shellcheck` -> `shellcheck`)."""
    module = fn.__module__
    if ".hooks." in module:
        return module.split(".hooks.")[-1]
    return fn.__name__


def hook_name(fn: Callable[..., Any]) -> str:
    """The name a hook is configured/gated under: `plugins.hooks.<hook_name>`.
    A hook is a function, so its identity is `__name__` — the callable parallel of
    a plugin tool's `plugin_tool_name` (one file may export several hooks, each its
    own config entry). The `config_model` for that entry comes from
    `@before/@after(config_model=…)`, or bare `ToolConfig` (enabled-only)."""
    return fn.__name__


def all_hooks() -> list[tuple[str, type[ToolConfig]]]:
    """Every distinct hook, as `(hook_name, config_model)` pairs for schema
    composition (`SolveigConfig.compose_plugin_hooks`). BEFORE/AFTER_HOOKS are keyed
    by *target tool*, so a hook registered for several tools appears under several
    keys but is ONE function — deduped by identity here. Two different hooks sharing
    a `__name__` would collide into one config entry; the later one is dropped with a
    warning (the schema key must be unique), matching how a plugin file names its
    tools uniquely."""
    seen: dict[str, Callable[..., Any]] = {}
    pairs: list[tuple[str, type[ToolConfig]]] = []
    for registry in (BEFORE_HOOKS, AFTER_HOOKS):
        for hooks in registry.values():
            for hook in hooks:
                name = hook_name(hook)
                if name in seen:
                    if seen[name] is not hook:
                        warnings.warn(
                            f"Two hooks named '{name}' — dropping the later one from "
                            f"config composition (hook config keys must be unique).",
                            stacklevel=2,
                        )
                    continue
                seen[name] = hook
                pairs.append((name, getattr(hook, "config_model", ToolConfig)))
    return pairs


def registered_plugin_names() -> set[str]:
    """All plugin names with at least one registered before/after hook - used to report load/skip status."""
    names = {plugin_name(hook) for hooks in BEFORE_HOOKS.values() for hook in hooks}
    names.update(plugin_name(hook) for hooks in AFTER_HOOKS.values() for hook in hooks)
    return names


def clear_hooks() -> None:
    """Drop all registered hooks - used before a plugin rescan/reload and in tests."""
    BEFORE_HOOKS.clear()
    AFTER_HOOKS.clear()


def before(
    tools: "tuple[str | type[BaseTool] | Callable[..., Any], ...]",
    *,
    config_model: type[ToolConfig] | None = None,
) -> Callable[[BeforeHook], BeforeHook]:
    """Register a before-hook for `tools`. `config_model=` declares a typed
    `plugins.hooks.<hook_name>` config schema (the callable parallel of a tool's
    `@tool(config_model=…)`); without it the hook gets bare `ToolConfig`
    (enabled-only). Either way the hook reads its config Any-style via
    `config.plugins.hooks.<name>`."""

    def register(fn: BeforeHook) -> BeforeHook:
        if config_model is not None:
            # A hook is a plain function with no BaseTool generic to auto-derive
            # from; stashing config_model here is how it opts into a typed schema.
            fn.config_model = config_model  # type: ignore[attr-defined]
        for target in tools:
            BEFORE_HOOKS[_tool_key(target)].append(fn)
        return fn

    return register


def after(
    tools: "tuple[str | type[BaseTool] | Callable[..., Any], ...]",
    *,
    config_model: type[ToolConfig] | None = None,
) -> Callable[[AfterHook], AfterHook]:
    """Register an after-hook for `tools`. See `before` for `config_model=`."""

    def register(fn: AfterHook) -> AfterHook:
        if config_model is not None:
            fn.config_model = config_model  # type: ignore[attr-defined]
        for target in tools:
            AFTER_HOOKS[_tool_key(target)].append(fn)
        return fn

    return register


def load_and_filter_plugin_hooks(config: SolveigConfig) -> list[str]:
    """Discover hook plugin modules into the hook registries — idempotent, UI-free.

    Returns discovery error messages for the caller to surface (reporting is a
    separate step). Hooks register via `@before`/`@after` at import and are
    enabled-by-default; per-hook gating (`plugins.hooks.<name>.enabled`) is enforced
    live in `run_tool_and_hooks`. `config` is kept on the signature for symmetry
    with the tool loader.
    """
    clear_hooks()
    _succeeded, _failed, errors = rescan_and_load_plugins("solveig.plugins.hooks")
    return errors


__all__ = [
    "before",
    "after",
    "clear_hooks",
    "plugin_name",
    "hook_name",
    "all_hooks",
    "registered_plugin_names",
    "load_and_filter_plugin_hooks",
]
