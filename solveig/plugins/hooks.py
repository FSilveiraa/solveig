"""Hook plugins — the `@before_tool`/`@after_tool` decorators and the config
they declare into.

The config section (`plugins.hooks`) is the hook registry: an entry carries the
hook that declared it (stamped as a `ClassVar` on the hook's config model), its
own `enabled` gate, and — through the stamped wrapper — where it applies.
Execution (`hooks_for`) filters the section at call time; a rescan is seen on
the next call because nothing is cached. There is no second registry to
transcribe into the config: a decorator records a declaration for the scan
(`solveig.plugins.scan`), and the scan types the entry after the imports.

Lives here, in the plugins package, so a hook plugin author imports the
decorators from their own package (`from solveig.plugins.hooks import
before_tool, after_tool`). The consumer on the tools side is
`run_tool_and_hooks` (`solveig/tools/orchestration.py`).

A hook is identified by its own function name (`hook_name`), which is also its
config key (`plugins.hooks.<name>`) — never by the file it came from.
"""

from __future__ import annotations

import warnings
from collections.abc import Awaitable, Callable
from enum import Enum, auto
from typing import Any, ClassVar

from pydantic import Field

from config import ConfigSection
from config.section.dynamic import DynamicSection
from solveig.interface.base import SolveigInterface
from solveig.plugins.scan import declare
from solveig.tools.base import BaseTool
from solveig.tools.result import ToolResult


class HookKind(Enum):
    """The point in the agent's life a hook intercepts.

    An enum, not a name: a member has a definition site, cannot be typo'd into
    a silently-empty filter, and is what an entry's stamped hook answers by.
    New kinds (a model request going out, a response coming back) are members
    here rather than new module-level dicts and new functions to walk them."""

    BEFORE_TOOL = auto()
    AFTER_TOOL = auto()


class HookConfig(ConfigSection):
    """The bare shape every hook's config starts as: the shared `enabled` flag,
    plus `hook` — the wrapper that declared this config model, stamped at
    declaration. `None` means no hook declared it: the entry is an unowned
    block, config for a hook that was never discovered — kept (it is the
    user's saved settings), shown by the Plugins report, and every reader that
    needs a hook skips it. The decorator gives each hook without an explicit
    `config_model` its own generated subclass, so the stamp is per hook and two
    bare hooks never share a class.

    NOTE: `hook` is annotated with a forward reference to `Hook`, defined
    below — a `ClassVar` is not a field, so nothing here needs it resolved, and
    pydantic leaves the annotation alone."""

    hook: ClassVar[Hook | None] = None
    enabled: bool = Field(default=True, description="Enable this hook")


BeforeHookFn = Callable[[dict[str, Any], HookConfig, SolveigInterface], Awaitable[None]]
AfterHookFn = Callable[
    [ToolResult, HookConfig, SolveigInterface], Awaitable[ToolResult]
]


def hooks_for(
    hooks: DynamicSection[HookConfig], kind: HookKind, tool_name: str
) -> list[tuple[Hook, HookConfig]]:
    """The hooks the section holds for `kind` applying to `tool_name`, each
    with its own config entry, in config order.

    The config section is the registry, so this is a filter, not a lookup: an
    entry counts when its stamped hook is of `kind`, its targets include
    `tool_name` (an empty targets tuple means every tool call), and the entry
    itself is `enabled`. Read at call time, never cached: a rescan replaces
    what the section holds and the next call has to see it."""
    return [
        (entry.hook, entry)
        for _name, entry in hooks
        if entry.hook is not None
        and entry.hook.kind is kind
        and (not entry.hook.targets or tool_name in entry.hook.targets)
        and entry.enabled
    ]


class Hook:
    """A hook as a callable object: `config_model` is DECLARED (on the class or
    by the decorator), not stashed on a function. `@before_tool`/`@after_tool`
    build these from plain functions; an author may also subclass directly.
    Identity is the instance (its `name`).

    `kind` is the class's declaration of when it runs; `targets` is the set of
    tool names the declaration named — empty meaning "every tool call", which
    is how a kind that narrows by nothing is expressed. Both are what the
    stamped config entry answers with, replacing the registry placement the
    config used to be transcribed from."""

    config_model: type[HookConfig] = HookConfig

    def __init__(self, fn: Callable[..., Any], name: str | None = None):
        self.fn = fn
        self.name = name or fn.__name__
        self.module = fn.__module__
        self.targets: tuple[str, ...] = ()

    def __call__(self, *args: Any) -> Any:
        return self.fn(*args)


class BeforeHook(Hook):
    fn: BeforeHookFn
    kind = HookKind.BEFORE_TOOL


class AfterHook(Hook):
    fn: AfterHookFn
    kind = HookKind.AFTER_TOOL


def _tool_key(target: str | type[BaseTool] | Callable[..., Any]) -> str:
    """The target key for a hook: the actual tool name a call is dispatched
    under (`call.tool_name`), not a Python identifier. A `BaseTool` subclass
    keys by `.tool_name()` (e.g. `CommandTool` -> `"command"`); a plain tool
    function (not-yet-converted plugin tools) keys by `__name__`, same as the
    string it's registered under."""
    if isinstance(target, str):
        return target
    if isinstance(target, type) and issubclass(target, BaseTool):
        return target.tool_name()
    return target.__name__


def declaring_hook[HookT: Hook](
    kind: HookKind, hook_cls: type[HookT]
) -> Callable[..., Callable[[Callable[..., Any]], HookT]]:
    """Build the decorator for one hook kind.

    Declaring a kind is declaring an enum member and calling this — the
    declaration is not rewritten per kind. `before_tool` and `after_tool` were
    two near-identical copies of the same six lines, which is how a third kind
    would have arrived too.

    Mirrors `subcommands.base.declaring_into`: which declaration an author
    makes is decided by WHICH decorator they import, never by an argument they
    pass."""

    def decorate(
        tools: tuple[str | type[BaseTool] | Callable[..., Any], ...] = (),
        *,
        config_model: type[HookConfig] | None = None,
    ) -> Callable[[Callable[..., Any]], HookT]:
        """`config_model=` declares a typed `plugins.hooks.<hook_name>` config
        schema on the hook class; without it the hook gets its own generated
        subclass of `HookConfig` (enabled-only), the same way a bare plugin
        tool gets its own parametrized `ToolConfig` — so the `hook` stamp on
        the config model is per hook, never shared. Either way the hook reads
        its config via `config.plugins.hooks.<name>`."""

        def register(fn: Callable[..., Any]) -> HookT:
            hook = hook_cls(fn)
            model = config_model
            if model is None:
                # A generated subclass keeps the stamp (and the schema) per
                #  hook: two bare hooks would otherwise both stamp the shared
                #  `HookConfig` class and the second entry would carry the
                #  first hook.
                model = type(hook.name, (HookConfig,), {})
            hook.config_model = model
            hook.targets = tuple(_tool_key(target) for target in tools)
            # The config model learns its hook from the act of being declared,
            #  like `ToolConfig` learns its tool from being subscripted. Two
            #  DIFFERENT hooks sharing one config model collide: both would
            #  read the same entry, so the first wins and the warning says so.
            if model.hook is not None and model.hook is not hook:
                warnings.warn(
                    f"The config model {model.__name__!r} is already stamped "
                    f"with the hook {model.hook.name!r}; the entry will carry "
                    f"the first. Rename one of the hooks.",
                    stacklevel=2,
                )
            else:
                model.hook = hook
            # The recording raises `RuntimeError` when no scan is running —
            #  there would be no scan to type the entry with.
            declare(hook.name, model, hook.module)
            return hook

        return register

    return decorate


before_tool = declaring_hook(HookKind.BEFORE_TOOL, BeforeHook)
"""Intercept a tool call before its body runs: inspect or transform the args,
or raise to block it."""

after_tool = declaring_hook(HookKind.AFTER_TOOL, AfterHook)
"""Intercept a tool's `ToolResult` on the way back: enrich or replace it."""


__all__ = [
    "AfterHook",
    "BeforeHook",
    "Hook",
    "HookConfig",
    "HookKind",
    "after_tool",
    "before_tool",
    "declaring_hook",
    "hooks_for",
]
