"""Assembles and runs the active toolset - the pipeline from raw tool
functions to the one
`Finalizer(HookRunner(FunctionToolset(...).filtered(...)))` object handed to
`Agent(toolsets=[...])`.


`HookRunner` is the middle stage of the same pipeline (raw tools -> hooks ->
active toolset); `AvailableTools.rebuild()` wires it directly into the stack
it builds. The `@before`/`@after` registry itself lives in
`solveig/plugins/hooks/__init__.py`, not here - a hook plugin author imports
from their own package, not from schema internals. `HookRunner` is just a
consumer of that registry, the same relationship `rebuild()` has with
`PLUGIN_TOOLS`. `WrapperToolset` itself is never exposed to hook authors -
`HookRunner` is the only thing that touches pydantic-ai's wrapper machinery.
A hook plugin just writes plain functions and targets tools by function or
by name:

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

from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.toolsets.wrapper import WrapperToolset

from solveig.context import SolveigContext
from solveig.plugins.hooks import AFTER_HOOKS, BEFORE_HOOKS, plugin_name
from solveig.tools.result import ToolResult


class HookRunner(WrapperToolset[SolveigContext]):
    """Runs registered `@before`/`@after` hooks (registry in
    `solveig/plugins/hooks/__init__.py`) around any wrapped tool call."""

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[SolveigContext],
        tool: ToolsetTool[SolveigContext],
    ) -> Any:
        config = ctx.deps.config
        interface = ctx.deps.interface

        for hook in BEFORE_HOOKS.get(name, ()):
            if plugin_name(hook) in config.plugins:
                await hook(tool_args, config, interface)

        result = await super().call_tool(name, tool_args, ctx, tool)

        if isinstance(result, ToolResult):
            for after_hook in AFTER_HOOKS.get(name, ()):
                if plugin_name(after_hook) in config.plugins:
                    result = await after_hook(result, config, interface)

        return result
