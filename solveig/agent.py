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

import json
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
from solveig.conversation import Conversation
from solveig.exceptions import PluginException
from solveig.interface import SolveigInterface
from solveig.llm.api import ProviderRef, get_model
from solveig.sessions.manager import SessionManager
from solveig.tools.available import AVAILABLE_TOOLS
from solveig.tools.base import BaseTool
from solveig.tools.orchestration import run_tool_and_hooks
from solveig.tools.result import ToolResult


def build_agent(
    config: SolveigConfig,
    provider_ref: ProviderRef,
    interface: SolveigInterface,
    system_prompt: str,
    conversation: Conversation,
    session_manager: SessionManager,
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
        # Bounds each individual model request at the provider client level -
        # not the whole run.py loop below, which also covers tool execution
        # and interactive ask_choice waits that have nothing to do with
        # network communication and shouldn't be timed out.
        model_settings={"timeout": config.timeout} if config.timeout else None,
        capabilities=[
            build_loop_capability(config, interface, conversation, session_manager),
            build_tool_execution_capability(),
        ],
    )


def build_loop_capability(
    config: SolveigConfig,
    interface: SolveigInterface,
    conversation: Conversation,
    session_manager: SessionManager,
) -> Hooks[SolveigContext]:
    """Build the per-agent capability driving live display, interleaving, and autonomy."""
    hooks: Hooks[SolveigContext] = Hooks()

    @hooks.on.model_request
    async def show_thinking_animation(ctx: RunContext[SolveigContext], *, request_context, handler):
        # Scoped to just this network round trip - tool execution (including
        # interactive ask_choice approval waits) happens outside this hook, so
        # Ctrl+C/Esc here cancels exactly the model call in flight, not
        # whatever else the run is doing, and the "Thinking" status/countdown
        # doesn't sit stuck on screen once the call returns.
        async with interface.with_cancellable(
            handler(request_context), status="Thinking", timeout=config.timeout
        ) as task:
            return await task

    @hooks.on.before_node_run
    async def display_new_response(ctx: RunContext[SolveigContext], node):
        if Agent.is_call_tools_node(node):
            # pydantic-ai has already appended this response to
            # ctx.state.message_history (the same list object conversation.messages
            # becomes) by the time this hook fires, so its index is stable.
            msg_index = len(ctx.messages) - 1
            await _display_response(
                interface, node.model_response, conversation, session_manager, msg_index
            )
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
    interface: SolveigInterface,
    model_response: ModelResponse,
    conversation: Conversation,
    session_manager: SessionManager,
    msg_index: int,
) -> None:
    renders_something = any(
        (isinstance(part, ThinkingPart | TextPart) and part.content.strip())
        for part in model_response.parts
    )
    if renders_something:
        await interface.display_section("Assistant")

    for part_index, part in enumerate(model_response.parts):
        if isinstance(part, ThinkingPart) and part.content.strip():
            await interface.display_text_box(
                part.content, title="Reasoning", collapsed=True, italic=True
            )
        elif isinstance(part, TextPart) and part.content.strip():
            await interface.display_comment(
                "assistant",
                part.content,
                conversation=conversation,
                session_manager=session_manager,
                msg_index=msg_index,
                part_index=part_index,
            )


def _tool_instance(args: dict[str, Any]) -> BaseTool | None:
    """The validated `BaseTool` instance for a class tool - pydantic-ai wraps a
    single model parameter as `{"params": <instance>}` (single-model-param
    flattening). `None` for a plain-function tool (mid-migration)."""
    if len(args) == 1:
        (only,) = args.values()
        if isinstance(only, BaseTool):
            return only
    return None


async def _run_mcp_tool(
    config: SolveigConfig,
    interface: SolveigInterface,
    call: ToolCallPart,
    args: dict[str, Any],
    handler: Any,
) -> Any:
    """Group + approve + display an MCP (or other untyped/plain-function)
    tool call - the same visibility and consent posture as a `BaseTool`, even
    though there's no typed schema here to build a proper header/decline
    `ToolResult` from. `call.tool_name` is already the sanitized, prefixed
    name (e.g. `search_parallel_ai_web_search`), good enough for a header on
    its own.

    Mirrors `ReadTool`'s negotiation shape (run+send / run+inspect-then-decide
    / don't run) rather than a flat yes/no - there's no "metadata only" middle
    ground here (no typed schema to split on), but the same idea of letting
    the user see the result before committing to sending it applies just as
    much to an arbitrary MCP call as to a file read. `handler`'s return value
    is passed through completely untouched when sent - only the *display* and
    *whether it's sent* are new here, nothing about the value itself changes.
    """
    async with interface.with_group(
        f"MCP: {call.tool_name}", auto_collapse=config.auto_collapse_tools
    ) as group:
        await group.display_text_box(
            json.dumps(args, indent=2, default=str), title="Args", language="json"
        )

        choice = await group.ask_choice(
            "Allow this MCP tool call?",
            [
                "Run and send result",
                "Run and inspect result first",
                "Don't run",
            ],
        )

        if choice == 2:
            await group.display_warning("Rejected")
            return "User declined to run this tool."

        async with group.with_cancellable(handler(args), status="Executing") as task:
            result = await task

        await group.display_text_box(
            str(result), title="Result", collapsed=choice == 0
        )

        if choice == 0:
            await group.display_success("Accepted")
            return result

        # choice == 1: ran and displayed the result above, now decide whether
        # to actually send it on.
        if (
            await group.ask_choice("Send this result to the assistant?", ["Yes", "No"])
        ) == 0:
            await group.display_success("Accepted")
            return result

        await group.display_warning("Rejected")
        return "User inspected the result and declined to send it to the assistant."


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
    renders the value the model sees.

    A plain-function tool (e.g. an MCP tool, or one a plugin author writes
    that way) has no `BaseTool` instance, so it can't go through
    `run_tool_and_hooks` - `_run_mcp_tool` gives it the same group/approve/
    display treatment generically, since there's no typed schema to build a
    tool-specific header or decline message from.

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
            return await _run_mcp_tool(config, interface, call, args, handler)

        try:
            # Cancellable like the model-request phase above, but no timeout -
            # a tool (including any interactive approval wait inside it) isn't
            # something that can time out, only something the user can cancel.
            async with interface.with_cancellable(
                run_tool_and_hooks(instance, config, interface), status="Executing"
            ) as task:
                result = await task
        except PluginException as e:
            raise ModelRetry(str(e)) from e

        if isinstance(result, ToolResult):
            return result.to_tool_return()
        return result

    return hooks
