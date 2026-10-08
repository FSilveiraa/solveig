"""Dependency-injection container passed as RunContext.deps to every tool
function and agent-level Hooks capability - the single place "stuff about
this run" lives, instead of each capability closing over its own subset.

`config` and `interface` are what a tool's `execute()` or a capability reads;
`cancelled` is the one thing written back. (It once also carried the live
`conversation`/`session_manager`, from before Solveig owned the agent loop and
delegated everything to hooks; nothing read them, so they're gone - the bar is
whether the run actually uses it, not how few fields there are.)"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from solveig.config import SolveigConfig
from solveig.interface.base import SolveigInterface


@dataclass
class SolveigContext:
    config: SolveigConfig
    interface: SolveigInterface

    cancelled: bool = False
    """The user asked to stop, and the run has not unwound yet.

    Written by the `tool_execute` hook, read by `run_turn` one step later. It
    exists because a cancelled tool call has to do two things that cannot
    compose in one statement: RETURN a tool result (a `ToolCallPart` with no
    matching `ToolReturnPart` is a malformed history that providers reject on
    the next request) and STOP the run. So the hook returns and records the
    intent here; `run_turn` raises `UserCancel` once the return part has landed.

    Per attempt by construction - `run_turn_with_retry` builds a fresh
    `SolveigContext` inside its retry loop, so nothing has to reset it.

    NOTE: only the assistant's own tool calls need this. Every other
    cancellable (a model request, `/mcp connect`, a `/tool` subcommand) owes no
    tool return, so its `UserCancel` just propagates to whoever owns it."""


def get_introspection_context(deps: SolveigContext) -> RunContext[SolveigContext]:
    """A RunContext wrapping real deps, for toolset introspection (e.g.
    `MCPToolset.get_tools()`) outside a real agent run. The model and usage
    are stand-ins, but deps are real, so `ctx.deps`-reading predicates (like
    the FilteredToolset's `is_tool_active`) behave as they would mid-run."""
    return RunContext(
        deps=deps,
        model=TestModel(),
        usage=RunUsage(),
        max_retries=1,
    )
