"""Builds the pydantic-ai Agent that drives a single conversation turn.

Cheap enough to rebuild per turn: the `Provider` (the real network client) is
held separately in a `ProviderRef` and reused across turns; only the `Agent`
wrapper (model + toolset + capabilities) is rebuilt, so runtime config changes
(model, briefing, disable_autonomy) take effect on the very next request
without restarting anything.

The `Agent` is given two per-turn `Hooks` capabilities (`build_*_capability`
below); both read live `config`/`interface`/`conversation`/`session_manager`
from `ctx.deps` (`SolveigContext`) at call time rather than closing over them:

- `build_loop_capability` - just the "Thinking" animation around each model
  request (`model_request` hook). The node-lifecycle hooks don't fire under
  `agent.iter()`, so response display is reactive (the transcript renders each
  adopted message) and the autonomy gate / comment interleaving are plain lines
  in `run_turn`'s loop, not hooks here.
- `build_tool_execution_capability` - per-tool-call concerns via the
  `tool_execute` hook: opens the tool's collapsible group, runs the plugin
  `@before`/`@after` hooks, and renders each `ToolResult` into the `ToolReturn`
  the model sees.
"""

import asyncio
import json
from typing import Any

from pydantic import ValidationError
from pydantic_ai import (
    Agent,
    ModelResponse,
    ModelRetry,
    RunContext,
)
from pydantic_ai.capabilities import Hooks
from pydantic_ai.exceptions import UnexpectedModelBehavior, UserError
from pydantic_ai.messages import ModelRequest, ToolCallPart, UserPromptPart
from pydantic_ai.models import Model
from pydantic_ai.tools import ToolDefinition

from solveig.api import ProviderRef, get_model
from solveig.config import SolveigConfig
from solveig.context import SolveigContext
from solveig.conversation import Conversation
from solveig.exceptions import PluginException, UserCancel
from solveig.interface import SolveigInterface
from solveig.sessions.manager import SessionManager
from solveig.tools.available import AVAILABLE_TOOLS
from solveig.tools.base import BaseTool
from solveig.tools.orchestration import run_tool_and_hooks
from solveig.tools.result import ToolResult


def build_agent(
    config: SolveigConfig,
    provider_ref: ProviderRef,
    system_prompt: str,
    model: Model | None = None,
) -> Agent[SolveigContext, str]:
    """Build the per-turn Agent.

    `model` lets callers (tests, the mock demo) inject a pydantic-ai `Model`
    directly (e.g. `FunctionModel`/`TestModel`), bypassing `provider_ref`'s
    Provider/API-key resolution entirely.

    Capabilities read everything they need (`interface`, `conversation`,
    `session_manager`, `config`) from `ctx.deps` (`SolveigContext`) at call
    time rather than closing over them here, so the same live values are
    available on both the loop-level and tool-execution hooks below.
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
            build_loop_capability(),
            build_tool_execution_capability(),
        ],
    )


def build_loop_capability() -> Hooks[SolveigContext]:
    """Build the per-agent capability driving the model-request animation.

    Only `model_request` (and the tool-execute capability's `tool_execute`)
    survive under `agent.iter()` - the graph node-lifecycle hooks
    (`before_node_run`/`after_node_run`) do NOT fire in iter mode, so response
    display and the autonomy/interleave logic live in `run_turn`'s explicit
    loop instead, not here."""
    hooks: Hooks[SolveigContext] = Hooks()

    @hooks.on.model_request
    async def show_thinking_animation(
        ctx: RunContext[SolveigContext], *, request_context, handler
    ):
        # Scoped to just this network round trip - tool execution (including
        # interactive ask_choice approval waits) happens outside this hook, so
        # Ctrl+C/Esc here cancels exactly the model call in flight, not
        # whatever else the run is doing, and the "Thinking" status/countdown
        # doesn't sit stuck on screen once the call returns.
        interface = ctx.deps.interface
        async with interface.with_cancellable(
            handler(request_context), status="Thinking", timeout=ctx.deps.config.timeout
        ) as task:
            return await task

    return hooks


async def run_turn(
    agent: Agent[SolveigContext, str],
    conversation: Conversation,
    deps: SolveigContext,
    prompt: str,
) -> None:
    """Core-owned per-turn loop. pydantic-ai remains the engine (model I/O,
    tool schemas + execution, consent via the tool_execute capability); this
    loop owns reconciliation into the reactive Conversation and the autonomy
    pause / interjection as plain lines.

    The user's prompt is appended up front so it renders instantly (optimistic
    echo) rather than only when the model run surfaces it. pydantic-ai creates
    its own equal-content request object for the prompt during the run;
    `reconcile()` folds that into the echo's id so `adopt` never mounts a
    duplicate. Everything else adopts by object identity, and a finally adopts
    once more so a mid-run cancel commits whatever completed (spec §8)."""
    echo_id = await conversation.append(
        ModelRequest(parts=[UserPromptPart(content=prompt)])
    )
    history = list(conversation.messages[:-1])  # everything before the echo
    anchor = len(history)  # pydantic-ai's own copy of the prompt lands here

    async with agent.iter(
        prompt,
        message_history=history,
        usage=conversation.usage,
        deps=deps,
    ) as run:

        async def sync() -> None:
            # Fold pydantic-ai's own request object for the prompt into the echo
            # id (idempotent) so it isn't mounted twice, then reconcile the
            # conversation to the run's authoritative messages.
            messages = run.all_messages()
            if len(messages) > anchor:
                conversation.reidentify(echo_id, messages[anchor])
            await conversation.adopt(messages)

        try:
            async for node in run:
                if deps.config.stream and Agent.is_model_request_node(node):
                    # Stream this response token-by-token into a live entry.
                    async with node.stream(run.ctx) as stream:
                        await sync()
                        await conversation.begin_stream(stream.response)
                        async for _event in stream:
                            await conversation.stream_updated()
                    continue

                # A CallToolsNode is the tool-round boundary. `run.next_node`
                # gives no lookahead in this loop (it mirrors the current node),
                # but a node that actually ran tool calls is *always* followed by
                # another model request, and a no-tool-call one goes straight to
                # End - so the response's tool calls tell us "more is coming"
                # without a peek.
                if Agent.is_call_tools_node(node):
                    # Swap the streamed (throwaway) object for pydantic-ai's
                    # canonical response under the same id, so adopt won't
                    # re-append it. No-op when streaming is off. The reactive
                    # transcript renders this response (text/reasoning) itself
                    # when adopt appends it - no imperative display here; the
                    # tool groups then render live inside the tool_execute hook.
                    await conversation.finalize_stream(node.model_response)
                    await sync()
                    await _gate_and_interleave(
                        deps,
                        run,
                        tools_ran=_response_has_tool_calls(node.model_response),
                    )
                    continue

                await sync()
        finally:
            await sync()


def _response_has_tool_calls(response: ModelResponse) -> bool:
    return any(isinstance(part, ToolCallPart) for part in response.parts)


async def _gate_and_interleave(
    deps: SolveigContext, run: Any, *, tools_ran: bool
) -> None:
    interface = deps.interface
    # Autonomy pause only mid-work: gate a round that actually ran tools (more
    # is coming), never the terminal no-tools node (the run is ending, nothing
    # to confirm). Gate before the drain so it consumes exactly the go-ahead it
    # waits for - draining first would let the always-on drain steal it and
    # leave the gate blocked forever.
    if deps.config.disable_autonomy and tools_ran:
        await interface.update_stats(status="Awaiting confirmation to continue")
        comment = await interface.dequeue_pending()
        await interface.update_stats(status=None)
        run.enqueue(comment, priority="asap")
    # Always-on drain: anything typed while tools ran (or while the gate was
    # blocked) is delivered at the next opportunity, in any autonomy mode -
    # including a comment that turns a would-be-terminating run into one more
    # round (priority='asap').
    while (queued := await interface.try_dequeue_pending()) is not None:
        run.enqueue(queued, priority="asap")


async def run_turn_with_retry(
    config: SolveigConfig,
    provider_ref: ProviderRef,
    interface: SolveigInterface,
    conversation: Conversation,
    session_manager: SessionManager,
    system_prompt: str,
    prompt: str,
    model: Model | None = None,
) -> bool:
    """Drive one conversation turn (build the per-turn Agent + run_turn) with
    retry on API failure. Returns True once the turn completes, False if it was
    cancelled or the user declined to retry.

    Sequential tool execution: Solveig's consent flow (ask_choice/with_group) is
    single-flight, but pydantic-ai runs a turn's tool calls concurrently by
    default, which two consent-requiring tools racing on the same interface
    state cannot tolerate. `parallel_tool_call_execution_mode("sequential")`
    just needs to be active in the ambient context around the run_turn await.
    Cancellation is owned per-phase inside agent.py (model request / tool exec),
    not wrapped here, so Ctrl+C/Esc cancels precisely what's running."""
    baseline = len(conversation.messages)
    while True:
        await asyncio.sleep(0)

        # On a retry, drop whatever the previous failed attempt added (the
        # optimistic-echo prompt + any partial responses) so this attempt starts
        # from the same clean state. A cancel returns below without looping, so a
        # cancelled turn keeps its partial.
        if len(conversation.messages) > baseline:
            await conversation.truncate_from(conversation.ids[baseline])

        agent = build_agent(config, provider_ref, system_prompt, model=model)
        deps = SolveigContext(
            config=config,
            interface=interface,
            conversation=conversation,
            session_manager=session_manager,
        )
        try:
            with Agent.parallel_tool_call_execution_mode("sequential"):
                await run_turn(agent, conversation, deps, prompt)
            return True
        except (asyncio.CancelledError, UserCancel):
            await interface.display_info("Request cancelled")
            return False
        except (UnexpectedModelBehavior, UserError, ValidationError) as e:
            await interface.display_error(str(e))
        except Exception as e:
            await interface.display_error(f"{e.__class__.__name__}: {e}")

        try:
            if not await _ask_retry(interface):
                return False
        except UserCancel:
            return False


async def _ask_retry(interface: SolveigInterface) -> bool:
    choice = await interface.ask_choice(
        "The API call failed. Do you want to retry?",
        choices=[
            "Yes, send the same message",
            "No, add a new message or run a sub-command",
        ],
        add_cancel=False,  # "No" already stops everything
    )
    return choice == 0


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

        await group.display_text_box(str(result), title="Result", collapsed=choice == 0)

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
