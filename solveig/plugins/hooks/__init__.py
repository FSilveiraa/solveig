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
the registry - the same relationship `available.build_toolset()` already has
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
from solveig.interface.base import SolveigInterface
from solveig.plugins.utils import rescan_and_load_plugins
from solveig.tools.base import BaseTool, ToolConfig
from solveig.tools.result import ToolResult

BeforeHookFn = Callable[
    [dict[str, Any], SolveigConfig, SolveigInterface], Awaitable[None]
]
AfterHookFn = Callable[
    [ToolResult, SolveigConfig, SolveigInterface], Awaitable[ToolResult]
]


class Hook:
    """A hook as a callable object: config_model is DECLARED on the class
    (default bare ToolConfig = enabled-only), not stashed on a function.
    `@before`/`@after` build these from plain functions; an author may also
    subclass directly. Identity is the instance (its `name`)."""

    config_model: type[ToolConfig] = ToolConfig

    def __init__(self, fn: Callable[..., Any], name: str | None = None):
        self.fn = fn
        self.name = name or fn.__name__
        self.module = fn.__module__

    def __call__(self, *args: Any) -> Any:
        return self.fn(*args)


class BeforeHook(Hook):
    fn: BeforeHookFn


class AfterHook(Hook):
    fn: AfterHookFn


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


def plugin_name(hook: Hook) -> str:
    """Derive a hook's owning plugin name from its module path (e.g.
    `solveig.plugins.hooks.shellcheck` -> `shellcheck`)."""
    if ".hooks." in hook.module:
        return hook.module.split(".hooks.")[-1]
    return hook.name


def hook_name(hook: Hook) -> str:
    """The name a hook is configured/gated under: `plugins.hooks.<hook_name>`.
    One file may export several hooks, each its own config entry."""
    return hook.name


def hooks_config_map() -> dict[str, type[ToolConfig]]:
    """Every distinct hook as {hook_name: config_model} for schema composition
    (`bootstrap.compose_plugin_hooks`). BEFORE/AFTER_HOOKS are keyed by
    *target tool*, so a hook registered for several tools appears under several
    keys but is ONE instance — deduped by name here. Two DIFFERENT hooks sharing
    a name collide into one config entry: both still FIRE (execution iterates
    the registries, not the schema), but they share the FIRST hook's gating —
    the warning names that consequence."""
    seen: dict[str, Hook] = {}
    configs: dict[str, type[ToolConfig]] = {}
    for registry in (BEFORE_HOOKS, AFTER_HOOKS):
        for hooks in registry.values():
            for hook in hooks:
                if hook.name in seen:
                    if seen[hook.name] is not hook:
                        warnings.warn(
                            f"Two different hooks named '{hook.name}' — both "
                            f"will run, but they share one config entry "
                            f"(plugins.hooks.{hook.name}, from the first): "
                            f"gating applies to both and the later hook's "
                            f"config_model is ignored. Rename one hook.",
                            stacklevel=2,
                        )
                    continue
                seen[hook.name] = hook
                configs[hook.name] = hook.config_model
    return configs


def registered_plugin_names() -> set[str]:
    """All plugin names with at least one registered before/after hook - used
    to report load/skip status."""
    names = {plugin_name(h) for hooks in BEFORE_HOOKS.values() for h in hooks}
    names.update(plugin_name(h) for hooks in AFTER_HOOKS.values() for h in hooks)
    return names


def clear_hooks() -> None:
    """Drop all registered hooks - used before a plugin rescan/reload and in tests."""
    BEFORE_HOOKS.clear()
    AFTER_HOOKS.clear()


def before(
    tools: "tuple[str | type[BaseTool] | Callable[..., Any], ...]",
    *,
    config_model: type[ToolConfig] | None = None,
) -> Callable[[BeforeHookFn], BeforeHook]:
    """Register a before-hook for `tools`. `config_model=` declares a typed
    `plugins.hooks.<hook_name>` config schema on the hook class; without it
    the hook gets bare `ToolConfig` (enabled-only). Either way the hook reads
    its config Any-style via `config.plugins.hooks.<name>`."""

    def register(fn: BeforeHookFn) -> BeforeHook:
        hook = BeforeHook(fn)
        if config_model is not None:
            hook.config_model = config_model
        for target in tools:
            BEFORE_HOOKS[_tool_key(target)].append(hook)
        return hook

    return register


def after(
    tools: "tuple[str | type[BaseTool] | Callable[..., Any], ...]",
    *,
    config_model: type[ToolConfig] | None = None,
) -> Callable[[AfterHookFn], AfterHook]:
    """Register an after-hook for `tools`. See `before` for `config_model=`."""

    def register(fn: AfterHookFn) -> AfterHook:
        hook = AfterHook(fn)
        if config_model is not None:
            hook.config_model = config_model
        for target in tools:
            AFTER_HOOKS[_tool_key(target)].append(hook)
        return hook

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
    "Hook",
    "BeforeHook",
    "AfterHook",
    "clear_hooks",
    "plugin_name",
    "hook_name",
    "hooks_config_map",
    "registered_plugin_names",
    "load_and_filter_plugin_hooks",
]
