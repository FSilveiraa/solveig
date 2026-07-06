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
from solveig.schema.tool._result import ToolResult

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
            await hook(tool_args, config, interface)

        result = await super().call_tool(name, tool_args, ctx, tool)

        if isinstance(result, ToolResult):
            for after_hook in _after_hooks.get(name, ()):
                result = await after_hook(result, config, interface)

        return result
