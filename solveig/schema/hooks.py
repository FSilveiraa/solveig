"""`@before`/`@after` hook registry and the `HookRunner` that drives it.

`WrapperToolset` itself is never exposed to hook authors - `HookRunner` is
the only thing that touches pydantic-ai's wrapper machinery. A hook plugin
just writes plain functions and targets tools by function or by name:

    @before(tools=(command,))
    async def check_something(tool_args, config, interface): ...

    @after(tools=("command",))
    async def rewrite_something(result: ToolResult, config, interface) -> ToolResult: ...

`@before` hooks run first; raising blocks the call (the wrapped tool never
runs). `@after` hooks run only if the call actually produced a `ToolResult`
(so they don't have to guard against pydantic-ai internals), and each gets
the previous hook's return value in registration order.

Hooks that need to carry state from their own `@before` to their own
`@after` (e.g. a duration-measuring plugin) own that plumbing themselves -
there's no runner-level pairing between the two, since not every hook
registers both (shellcheck is before-only, trafilatura is after-only).
"""

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.toolsets.wrapper import WrapperToolset

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.deps import SolveigDeps
from solveig.schema.result import ToolResult

BeforeHook = Callable[
    [dict[str, Any], SolveigConfig, SolveigInterface], Awaitable[None]
]
AfterHook = Callable[
    [ToolResult, SolveigConfig, SolveigInterface], Awaitable[ToolResult]
]

_before_hooks: dict[str, list[BeforeHook]] = defaultdict(list)
_after_hooks: dict[str, list[AfterHook]] = defaultdict(list)


def _tool_key(target: str | Callable[..., Any]) -> str:
    return target if isinstance(target, str) else target.tool_name  # type: ignore[attr-defined]


def _plugin_name(fn: Callable[..., Any]) -> str:
    """Derive a hook's owning plugin name from its module path (e.g. `solveig.plugins.hooks.shellcheck` -> `shellcheck`)."""
    module = fn.__module__
    if ".hooks." in module:
        return module.split(".hooks.")[-1]
    return fn.__name__


def registered_plugin_names() -> set[str]:
    """All plugin names with at least one registered before/after hook - used to report load/skip status."""
    names = {_plugin_name(hook) for hooks in _before_hooks.values() for hook in hooks}
    names.update(
        _plugin_name(hook) for hooks in _after_hooks.values() for hook in hooks
    )
    return names


def clear_hooks() -> None:
    """Drop all registered hooks - used before a plugin rescan/reload and in tests."""
    _before_hooks.clear()
    _after_hooks.clear()


def before(
    tools: tuple[str | Callable[..., Any], ...],
) -> Callable[[BeforeHook], BeforeHook]:
    def register(fn: BeforeHook) -> BeforeHook:
        for target in tools:
            _before_hooks[_tool_key(target)].append(fn)
        return fn

    return register


def after(
    tools: tuple[str | Callable[..., Any], ...],
) -> Callable[[AfterHook], AfterHook]:
    def register(fn: AfterHook) -> AfterHook:
        for target in tools:
            _after_hooks[_tool_key(target)].append(fn)
        return fn

    return register


class HookRunner(WrapperToolset[SolveigDeps]):
    """Runs registered `@before`/`@after` hooks around any wrapped tool call."""

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[SolveigDeps],
        tool: ToolsetTool[SolveigDeps],
    ) -> Any:
        config = ctx.deps.config
        interface = ctx.deps.interface

        for hook in _before_hooks.get(name, ()):
            if _plugin_name(hook) in config.plugins:
                await hook(tool_args, config, interface)

        result = await super().call_tool(name, tool_args, ctx, tool)

        if isinstance(result, ToolResult):
            for after_hook in _after_hooks.get(name, ()):
                if _plugin_name(after_hook) in config.plugins:
                    result = await after_hook(result, config, interface)

        return result
