"""Assembles and runs the active toolset - the pipeline from raw tool
functions to the one
`Finalizer(HookRunner(FunctionToolset(...).filtered(...)))` object handed to
`Agent(toolsets=[...])`.

`AVAILABLE_TOOLS.rebuild(config)` only needs to be called after a genuine
change in tool *membership*: plugin modules (re)scanned (new tools may now
exist that didn't before) or an MCP server connecting/disconnecting (whole
new toolsets of previously-unknown tools appearing/disappearing). It does
NOT need to be called for `config.no_commands` or `config.plugins`
toggling - visibility for those is decided live, per step, by the
`FilteredToolset` wrapped around the base `FunctionToolset`, using whatever
`ctx.deps.config` says *right now*. This is deliberately built on
pydantic-ai's own `FilteredToolset` rather than a hand-rolled visibility
check, since "hide some already-known tools based on live config" is exactly
what it's for.

`HookRunner` and the `@before`/`@after` registry live here too - they're the
middle stage of the same pipeline (raw tools -> hooks -> active toolset),
and `AvailableTools.rebuild()` wires `HookRunner` directly into the stack it
builds. `WrapperToolset` itself is never exposed to hook authors -
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

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai.toolsets.wrapper import WrapperToolset

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.deps import SolveigContext, SolveigDeps
from solveig.schema.tools import CORE_TOOLS, command
from solveig.schema.tools.result import Finalizer, ToolResult

# MCP tools are appended here when an MCP server connects, removed on disconnect.
# Call AVAILABLE_TOOLS.rebuild(config) after mutating.
MCP_TOOLS: list = []

# ---------------------------------------------------------------------------
# @before / @after hook registry
# ---------------------------------------------------------------------------

BeforeHook = Callable[
    [dict[str, Any], SolveigConfig, SolveigInterface], Awaitable[None]
]
AfterHook = Callable[
    [ToolResult, SolveigConfig, SolveigInterface], Awaitable[ToolResult]
]

_before_hooks: dict[str, list[BeforeHook]] = defaultdict(list)
_after_hooks: dict[str, list[AfterHook]] = defaultdict(list)


def _tool_key(target: str | Callable[..., Any]) -> str:
    return target if isinstance(target, str) else target.__name__


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
        ctx: SolveigContext,
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


# ---------------------------------------------------------------------------
# Active toolset assembly
# ---------------------------------------------------------------------------


class AvailableTools:
    """Holds the currently active toolset, rebuilt from the current tool sources."""

    def __init__(self) -> None:
        self._toolset: Finalizer | None = None

    def rebuild(self, config: SolveigConfig) -> None:
        """Recompute the base toolset from CORE_TOOLS, every discovered plugin
        tool, and MCP_TOOLS. Only needed after tool *membership* actually
        changes - see the module docstring for why `no_commands`/`config.plugins`
        toggling doesn't need this."""
        # Local import: solveig.plugins imports solveig.plugins.hooks, which
        # imports clear_hooks/registered_plugin_names from this module - a
        # module-level import here would be circular.
        from solveig.plugins.tools import PLUGIN_TOOLS

        # Every discovered plugin tool is included here, not just the ones
        # config.plugins currently enables - the filter below decides
        # visibility live, per step, from config.
        all_tools = [*CORE_TOOLS, *PLUGIN_TOOLS.all.values(), *MCP_TOOLS]

        if not all_tools:
            raise ValueError("No tools available: the tool list is empty.")

        def is_tool_active(ctx: SolveigContext, tool_def: ToolDefinition) -> bool:
            active_config = ctx.deps.config
            if tool_def.name == command.__name__ and active_config.no_commands:
                return False
            plugin_name = PLUGIN_TOOLS.owners.get(tool_def.name)
            if plugin_name is not None and plugin_name not in active_config.plugins:
                return False
            return True

        base = FunctionToolset(all_tools).filtered(is_tool_active)
        self._toolset = Finalizer(HookRunner(base))

    @property
    def toolset(self) -> Finalizer:
        assert self._toolset is not None, "Call rebuild() before accessing toolset"
        return self._toolset


AVAILABLE_TOOLS = AvailableTools()
