"""Hook plugin registry - the `@before_tool`/`@after_tool` decorators and the state
they register into.

Lives here, in the plugins package, so a hook plugin author imports the
decorators from their own package (`from solveig.plugins.hooks import
before_tool, after_tool`) instead of reaching into tools internals - mirroring
`PLUGIN_TOOLS`/`tool` in `plugins/tools.py`. The consumer on the tools side is
`run_tool_and_hooks` (`solveig/tools/orchestration.py`): it reads `HOOKS` at
call time to run the registered hooks around a tool call, but doesn't own it -
the same relationship `available.build_toolset()` already has with
`PLUGIN_TOOLS`.

Keyed by KIND first, then by however many keys that kind narrows on - one tool
name for the tool kinds, so a hook may target several tools and several hooks
may target one. A tool call is one point in the agent's life among several - a
request going out to the model, a response coming back - so a new kind is a
`HookKind` member and a `declaring_hook` call, with its own nesting depth, not
another module-level dict. A hook is identified by its own function name (`hook_name`), which is also its config key
(`plugins.hooks.<name>`) - never by the file it came from. Nothing here derives
anything from a module path.
"""

import warnings
from collections.abc import Awaitable, Callable, Iterator
from enum import Enum, auto
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
    `@before_tool`/`@after_tool` build these from plain functions; an author may also
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


class HookKind(Enum):
    """The point in the agent's life a hook intercepts.

    An enum, not a name: a member has a definition site, cannot be typo'd into
    a silently-empty registry entry, and is what the registry is keyed by. New
    kinds (a model request going out, a response coming back) are members here
    rather than new module-level dicts and new functions to walk them."""

    BEFORE_TOOL = auto()
    AFTER_TOOL = auto()


HookTree = list[Hook] | dict[str, "HookTree"]
"""What a kind holds. Depth is the KIND's business, not the registry's: tool
hooks narrow by tool name, so `BEFORE_TOOL` holds `{tool_name: [hooks]}`; a kind
with nothing to narrow by holds `[hooks]` directly, and one that narrows twice
nests twice. Fixing a single level here would make the first kind that doesn't
fit rewrite everything that walks it."""

HOOKS: dict[HookKind, HookTree] = {}


def hooks_for(kind: HookKind, *path: str) -> list[Hook]:
    """The hooks registered under `kind` at `path`, in declaration order.

    `path` is however many keys that kind nests by - one tool name for the tool
    kinds, nothing for a kind that fires unconditionally. An unregistered path
    is empty, never an error: asking is how a caller finds out.

    Read at call time, never cached: a plugin rescan replaces what is in the
    registry and the next call has to see it."""
    node: HookTree | None = HOOKS.get(kind)
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, list) else []


def _add_hook(kind: HookKind, hook: Hook, *path: str) -> None:
    """Append `hook` under `kind` at `path`, creating the nesting it implies."""
    if not path:
        leaf = HOOKS.setdefault(kind, [])
        assert isinstance(leaf, list), f"{kind} is registered with a deeper path"
        leaf.append(hook)
        return
    node = HOOKS.setdefault(kind, {})
    for key in path[:-1]:
        assert isinstance(node, dict), f"{kind} is registered with a shallower path"
        node = node.setdefault(key, {})
    assert isinstance(node, dict), f"{kind} is registered with a shallower path"
    node.setdefault(path[-1], []).append(hook)  # type: ignore[union-attr]


def _walk_hooks(node: HookTree) -> Iterator[Hook]:
    """Every hook under `node`, whatever depth it sits at."""
    if isinstance(node, list):
        yield from node
        return
    for child in node.values():
        yield from _walk_hooks(child)


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
    (`bootstrap.compose_plugin_hooks`). A hook registered for several tools appears
    under several keys but is ONE instance — deduped by name here. Two DIFFERENT hooks sharing
    a name collide into one config entry: both still FIRE (execution iterates
    the registries, not the schema), but they share the FIRST hook's gating —
    the warning names that consequence."""
    seen: dict[str, Hook] = {}
    configs: dict[str, type[ToolConfig]] = {}
    for tree in HOOKS.values():
        for hook in _walk_hooks(tree):
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
    """Drop all registered hooks - used before a plugin rescan/reload and in
    tests. Clears every kind, including ones added after this was written."""
    HOOKS.clear()


def declaring_hook[HookT: Hook](
    kind: HookKind, hook_cls: type[HookT]
) -> Callable[..., Callable[[Callable[..., Any]], HookT]]:
    """Build the decorator for one hook kind.

    Declaring a kind is declaring an enum member and calling this - the
    registration is not rewritten per kind. `before_tool` and `after_tool` were
    two near-identical copies of the same six lines, which is how a third kind
    would have arrived too.

    Mirrors `subcommands.base.declaring_into`: which registry a declaration
    lands in is decided by WHICH decorator the author imports, never by an
    argument they pass."""

    def decorate(
        tools: "tuple[str | type[BaseTool] | Callable[..., Any], ...]" = (),
        *,
        config_model: type[ToolConfig] | None = None,
    ) -> Callable[[Callable[..., Any]], HookT]:
        """`config_model=` declares a typed `plugins.hooks.<hook_name>` config
        schema on the hook class; without it the hook gets bare `ToolConfig`
        (enabled-only). Either way the hook reads its config Any-style via
        `config.plugins.hooks.<name>`."""

        def register(fn: Callable[..., Any]) -> HookT:
            hook = hook_cls(fn)
            if config_model is not None:
                hook.config_model = config_model
            if not tools:
                # A kind that narrows by nothing: one list, no nesting.
                _add_hook(kind, hook)
            for target in tools:
                _add_hook(kind, hook, _tool_key(target))
            return hook

        return register

    return decorate


before_tool = declaring_hook(HookKind.BEFORE_TOOL, BeforeHook)
"""Intercept a tool call before its body runs: inspect or transform the args,
or raise to block it."""

after_tool = declaring_hook(HookKind.AFTER_TOOL, AfterHook)
"""Intercept a tool's `ToolResult` on the way back: enrich or replace it."""


__all__ = [
    "HOOKS",
    "AfterHook",
    "BeforeHook",
    "Hook",
    "HookKind",
    "after_tool",
    "before_tool",
    "clear_hooks",
    "declaring_hook",
    "hook_name",
    "hooks_config_map",
    "hooks_for",
]
