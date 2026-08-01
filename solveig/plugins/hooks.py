"""Hook plugin registry - the `@before`/`@after` decorators and the state
they register into.

Lives here, in the plugins package, so a hook plugin author imports the
decorators from their own package (`from solveig.plugins.hooks import before,
after`) instead of reaching into tools internals - mirroring `PLUGIN_TOOLS`/
`tool` in `plugins/tools.py`. The consumer on the tools side is
`run_tool_and_hooks` (`solveig/tools/orchestration.py`): it reads
`BEFORE_HOOKS`/`AFTER_HOOKS` at call time to run the registered hooks around a
tool call, but doesn't own the registry - the same relationship
`available.build_toolset()` already has with `PLUGIN_TOOLS`.

Keyed by the *tool being hooked* (name or class), appended to a list, so one
hook may target several tools and several hooks may target one. A hook is
identified by its own function name (`hook_name`), which is also its config key
(`plugins.hooks.<name>`) - never by the file it came from. Nothing here derives
anything from a module path.
"""

import warnings
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from solveig.config import SolveigConfig
from solveig.interface.base import SolveigInterface
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


__all__ = [
    "before",
    "after",
    "Hook",
    "BeforeHook",
    "AfterHook",
    "clear_hooks",
    "hook_name",
    "hooks_config_map",
]
