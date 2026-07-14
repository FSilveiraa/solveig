"""Builds the pydantic-ai Agent that drives a single conversation turn.

Cheap enough to rebuild per turn: the `Provider` (the real network client) is
held separately in a `ProviderRef` and reused across turns; only the `Agent`
wrapper (model + toolset + capabilities) is rebuilt, so runtime config changes
(model, briefing, disable_autonomy) take effect on the very next request
without restarting anything.

The `Agent` is given two per-turn `Hooks` capabilities (`build_*_capability`
below), both fresh each turn so live `config`/`interface` are captured:

- `build_loop_capability` - loop-level concerns via node hooks: live display of
  each model response (thinking/text), the autonomy gate (block between rounds
  when `disable_autonomy`), and comment interleaving (`ctx.enqueue`).
- `build_tool_execution_capability` - per-tool-call concerns via tool-execute
  hooks: opens the tool's collapsible group, runs the plugin `@before`/`@after`
  hooks, and renders each `ToolResult` into the `ToolReturn` the model sees.
  This replaces the old `HookRunner`/`Finalizer` `WrapperToolset` stack.
"""

from typing import Any

from pydantic_ai import (
    Agent,
    ModelResponse,
    ModelRetry,
    RunContext,
    TextPart,
    ThinkingPart,
)
from pydantic_ai.capabilities import Hooks
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.tools import ToolDefinition
from pydantic_graph import End

from solveig.config import SolveigConfig
from solveig.context import SolveigContext
from solveig.exceptions import PluginException
from solveig.interface import SolveigInterface
from solveig.llm.api import ProviderRef, get_model
from solveig.tools.available import AVAILABLE_TOOLS
from solveig.tools.base import BaseTool
from solveig.tools.orchestration import run_tool_and_hooks
from solveig.tools.result import ToolResult


def build_agent(
    config: SolveigConfig,
    provider_ref: ProviderRef,
    interface: SolveigInterface,
    system_prompt: str,
    model: Model | None = None,
) -> Agent[SolveigContext, str]:
    """Build the per-turn Agent.

    `model` lets callers (tests, the mock demo) inject a pydantic-ai `Model`
    directly (e.g. `FunctionModel`/`TestModel`), bypassing `provider_ref`'s
    Provider/API-key resolution entirely.
    """
    if model is not None:
        resolved_model = model
    else:
        assert config.model is not None, "build_agent requires config.model to be set"
        resolved_model = get_model(config.api_type, provider_ref.provider, config.model)
    return Agent(
        resolved_model,
        deps_type=SolveigContext,
        instructions=system_prompt,
        toolsets=[AVAILABLE_TOOLS.toolset],
        capabilities=[
            build_loop_capability(config, interface),
            build_tool_execution_capability(),
        ],
    )


def build_loop_capability(
    config: SolveigConfig, interface: SolveigInterface
) -> Hooks[SolveigContext]:
    """Build the per-agent capability driving live display, interleaving, and autonomy."""
    hooks: Hooks[SolveigContext] = Hooks()

    @hooks.on.before_node_run
    async def display_new_response(ctx: RunContext[SolveigContext], node):
        if Agent.is_call_tools_node(node):
            await _display_response(interface, node.model_response)
        return node

    @hooks.on.after_node_run
    async def gate_and_interleave(ctx: RunContext[SolveigContext], node, result):
        # Both concerns only apply at the CallToolsNode -> next-node boundary
        # - the point where tool execution for this round has just finished.
        # Draining after every node (e.g. right after UserPromptNode, before
        # any tool has even run) would steal a pre-typed comment before the
        # autonomy gate below ever gets a chance to consume it.
        if not Agent.is_call_tools_node(node):
            return result

        queue = interface.pending_queue

        # Autonomy gate first, so it consumes exactly the go-ahead it's
        # waiting for - draining the queue before this point would let the
        # always-on drain below steal it and leave the gate blocked forever.
        if config.disable_autonomy and not isinstance(result, End):
            await interface.update_stats(status="Awaiting confirmation to continue")
            comment = await queue.get()
            await interface.notify_pending_queue_changed()
            await interface.update_stats(status=None)
            ctx.enqueue(comment, priority="asap")

        # Always-on drain: anything else typed - while this round of tools
        # was executing, or freshly arrived while the gate above was blocked
        # - gets delivered at the next opportunity too, regardless of
        # autonomy mode.
        while not queue.empty():
            ctx.enqueue(queue.get_nowait(), priority="asap")
            await interface.notify_pending_queue_changed()

        return result

    return hooks


async def _display_response(
    interface: SolveigInterface, model_response: ModelResponse
) -> None:
    for part in model_response.parts:
        if isinstance(part, ThinkingPart) and part.content:
            await interface.display_text_box(
                part.content, title="Reasoning", collapsed=True, italic=True
            )
        elif isinstance(part, TextPart) and part.content:
            await interface.display_section("Assistant")
            await interface.display_comment(part.content)


def _tool_instance(args: dict[str, Any]) -> BaseTool | None:
    """The validated `BaseTool` instance for a class tool - pydantic-ai wraps a
    single model parameter as `{"params": <instance>}` (single-model-param
    flattening). `None` for a plain-function tool (mid-migration)."""
    if len(args) == 1:
        (only,) = args.values()
        if isinstance(only, BaseTool):
            return only
    return None


def build_tool_execution_capability() -> Hooks[SolveigContext]:
    """Per-tool-call capability: opens each call's collapsible group, runs the
    plugin `@before`/`@after` hooks, and renders the `ToolResult` into a
    `ToolReturn`. Replaces the old `HookRunner`/`Finalizer` `WrapperToolset`
    stack with pydantic-ai's native `wrap_tool_execute` hook.

    The group + hook flow itself lives in `run_tool_and_hooks`
    (`solveig/tools/orchestration.py`), shared with the `/tool` subcommand path
    so a manually-typed `/command` runs the same shellcheck a model call does.
    This capability supplies the LLM-specific parts: the body is pydantic-ai's
    own `handler(args)`, a blocking `PluginException` becomes a `ModelRetry`
    (the model's cue to react), and the terminal `ToolResult.to_tool_return()`
    renders the value the model sees. Non-`ToolResult` returns (MCP tools) pass
    through untouched.

    A plain-function tool (should a plugin author write one) has no `BaseTool`
    instance, so it can't be group-wrapped or hooked here - it runs bare via
    `handler`, responsible for its own display, as before.

    Stateless: `config`/`interface` come from `ctx.deps` and the hook
    registries are read live at call time, so a plugin rescan or
    `config.plugins` toggle takes effect on the next call.
    """
    hooks: Hooks[SolveigContext] = Hooks()

    @hooks.on.tool_execute
    async def run_tool(
        ctx: RunContext[SolveigContext],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        handler: Any,
    ) -> Any:
        config, interface = ctx.deps.config, ctx.deps.interface
        instance = _tool_instance(args)

        if instance is None:
            return await handler(args)

        try:
            result = await run_tool_and_hooks(
                instance, config, interface, lambda: handler(args)
            )
        except PluginException as e:
            raise ModelRetry(str(e)) from e

        if isinstance(result, ToolResult):
            return result.to_tool_return()
        return result

    return hooks
