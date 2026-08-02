"""Builds the pydantic-ai Agent that drives a single conversation turn.

Cheap enough to rebuild per turn: the `Provider` (the real network client) is
held separately in a `Client` and reused across turns; only the `Agent`
wrapper (model + toolset + capabilities) is rebuilt, so runtime config changes
(model, briefing, disable_autonomy) take effect on the very next request
without restarting anything.

The `Agent` is given two per-turn `Hooks` capabilities (`build_*_capability`
below); both read live `config`/`interface` from `ctx.deps` (`SolveigContext`)
at call time rather than closing over them:

- `build_loop_capability` - just the "Thinking" animation around each model
  request (`model_request` hook). The node-lifecycle hooks don't fire under
  `agent.iter()`, so response display is reactive (the transcript renders each
  adopted message) and the autonomy gate / comment interleaving are plain lines
  in `run_turn`'s loop, not hooks here.
- `build_tool_execution_capability` - per-tool-call concerns via the
  `tool_execute` hook: opens the tool's collapsible group, runs the plugin
  `@before_tool`/`@after_tool` hooks, and renders each `ToolResult` into the `ToolReturn`
  the model sees.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
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
from pydantic_ai.messages import (
    FunctionToolResultEvent,
    ModelMessage,
    ModelRequest,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.tools import ToolDefinition
from pydantic_graph import End

from solveig.api.client import Client
from solveig.config import SolveigConfig
from solveig.context import SolveigContext
from solveig.exceptions import PluginException, ToolDisabledError, UserCancel
from solveig.interface.base import SolveigInterface
from solveig.session.conversation import Conversation, MessageId
from solveig.tools.available import build_toolset
from solveig.tools.base import BaseTool
from solveig.tools.orchestration import run_tool_and_hooks, run_untyped_tool
from solveig.tools.result import ToolResult
from solveig.user_message_queue import UserMessageQueue


def build_agent(
    config: SolveigConfig,
    client: Client,
    system_prompt: str,
    model: Model | None = None,
) -> Agent[SolveigContext, str]:
    """Build the per-turn Agent.

    `model` lets callers (tests, the mock demo) inject a pydantic-ai `Model`
    directly (e.g. `FunctionModel`/`TestModel`), bypassing `provider_ref`'s
    Provider/API-key resolution entirely.

    Capabilities read everything they need (`config`, `interface`) from
    `ctx.deps` (`SolveigContext`) at call time rather than closing over them
    here, so the same live values are available on both the loop-level and
    tool-execution hooks below.
    """
    if model is not None:
        resolved_model = model
    else:
        assert config.api.model is not None, (
            "build_agent requires config.api.model to be set"
        )
        resolved_model = config.api.type.get_model(client.provider, config.api.model)
    return Agent(
        resolved_model,
        deps_type=SolveigContext,
        instructions=system_prompt,
        toolsets=[build_toolset(config)],
        # Bounds each individual model request at the provider client level -
        # not the whole run.py loop below, which also covers tool execution
        # and interactive ask_choice waits that have nothing to do with
        # network communication and shouldn't be timed out.
        model_settings={"timeout": config.api.timeout} if config.api.timeout else None,
        capabilities=[
            build_loop_capability(),
            build_tool_execution_capability(),
        ],
    )


def _thinking(interface: SolveigInterface, awaitable: Any, timeout: float | None):
    """The single 'Thinking' animation + cancellable policy (status text +
    timeout), invoked from the two irreducible sites below.

    Why two sites and not one: pydantic-ai's documented streaming pattern is
    `async for node in run` with `node.stream()` inside. A NON-streamed model
    request therefore executes inside the loop's `__anext__` - the `model_request`
    hook is the only clean seam to wrap *that*. A STREAMED response, by contrast,
    must cancel the READER (in run_turn), never the parked stream handler:
    cancelling the handler would tear the open HTTP stream mid-read (ReadError)
    and leave a stray partial that adopt() duplicates - so it can't go through the
    hook. Same animation either way; kept here so the policy is single-sourced."""
    return interface.with_cancellable(awaitable, status="Thinking", timeout=timeout)


def build_loop_capability() -> Hooks[SolveigContext]:
    """Build the per-agent capability driving the (non-stream) model-request
    animation via the `model_request` hook.

    Stateless, so it lives on the Agent. The concerns that need THIS run's
    conversation state (reconciliation, the autonomy gate) are a separate
    per-run capability - `build_run_capability` below."""
    hooks: Hooks[SolveigContext] = Hooks()

    @hooks.on.model_request
    async def show_thinking_animation(
        ctx: RunContext[SolveigContext], *, request_context, handler
    ):
        # Non-stream: wrap the network round trip so Esc/Ctrl+C cancels exactly
        # the model call in flight. Streaming steps aside - run_turn owns the
        # reader-side animation instead (see _thinking for the full why).
        if ctx.deps.config.interface.stream:
            return await handler(request_context)
        async with _thinking(
            ctx.deps.interface, handler(request_context), ctx.deps.config.api.timeout
        ) as task:
            return await task

    return hooks


@dataclass
class _PlacedComment:
    """A comment and the tool call it arrived behind.

    Recorded when it happens, not derived afterwards. The alternative - reading
    the position back out of the assembled message's part order - would make a
    display-side artifact load-bearing, and re-derives a fact we held at the
    moment it was true. `after` is None for a comment that arrived before any
    tool finished."""

    text: str
    after: str | None


@dataclass
class _Reconciler:
    """Folds pydantic-ai's authoritative message list into the reactive
    Conversation.

    Lifted out of `run_turn`'s closure ahead of the loop migration: under
    `agent.run()` the same list arrives as `RunContext.messages`, so this body
    becomes the `after_node_run` hook unchanged. Holding `echo_id`/`anchor` on
    an object rather than closing over them is the whole point - a hook has no
    enclosing scope to capture them from."""

    conversation: Conversation
    echo_id: MessageId
    anchor: int
    """Index where pydantic-ai's own copy of the prompt lands."""
    placed: list[_PlacedComment] = field(default_factory=list)
    """Comments delivered during the current step, each with the tool call it
    arrived behind. Recorded by `_assemble_tool_returns` as it happens, replayed
    into the canonical message below, cleared once that message exists."""

    async def sync(self, messages: Sequence[ModelMessage]) -> None:
        # Fold pydantic-ai's own request object for the prompt into the echo id
        # (idempotent) so it isn't mounted twice, then reconcile the
        # conversation to the run's authoritative messages.
        if len(messages) > self.anchor:
            await self.conversation.reidentify(self.echo_id, messages[self.anchor])
        await self._fold_assembly(messages)
        await self.conversation.adopt(messages)

    async def _fold_assembly(self, messages: Sequence[ModelMessage]) -> None:
        """Reconcile the tool-return entry we assembled as tools finished with
        pydantic-ai's canonical one, built in one go when the node ended.

        Two things have to be true at once, which is why this is not a swap: the
        entry must end up being pydantic-ai's OBJECT (adopt matches by identity,
        so a copy mounts a duplicate of every tool return), and it must keep the
        user comments, which exist nowhere else. So the comments are replayed
        INTO that object and it goes on being pydantic-ai's. Mutating `parts` is
        what makes both true, and it is also what puts the comments on the wire
        in the order they happened.

        Identified by shape, not position: pydantic-ai appends that request to
        the history only when the NEXT ModelRequestNode runs, so it is not the
        trailing message at the boundary where the tools actually finished - and
        by the time it IS trailing, a response has landed behind it. A step
        produces exactly one unheld request carrying tool returns."""
        if not self.conversation.assembling:
            return
        placed, self.placed = self.placed, []
        held = {id(message) for message in self.conversation.messages}
        for message in messages:
            if id(message) in held or not isinstance(message, ModelRequest):
                continue
            if not any(isinstance(part, ToolReturnPart) for part in message.parts):
                continue
            await self.conversation.finalize_assembly(
                message,
                merge=lambda _ours, theirs: _with_comments(theirs, placed),
            )
            return
        # No canonical message yet - this step's comments are still owed.
        self.placed = placed


async def _stream_response(
    conversation: Conversation,
    node: Any,
    run_ctx: Any,
    on_start: Callable[[], Awaitable[None]],
) -> None:
    """Consume one streamed model response into a live Conversation entry.

    Extracted ahead of the loop migration: under `agent.run()` this becomes the
    `event_stream_handler`, where the same content arrives as `PartDeltaEvent`s
    to accumulate rather than per-access `stream.response` snapshots. The
    cancellation shape survives that change unchanged - the caller wraps this
    whole consumption in one cancellable task so Esc/Ctrl+C stops the READER
    and lets the stream's context close the HTTP stream in order (why the
    reader, not the handler: see `_thinking`)."""
    async with node.stream(run_ctx) as stream:
        await on_start()
        await conversation.begin_stream(stream.response)
        async for _event in stream:
            await conversation.stream_updated(stream.response)


def _with_comments(
    canonical: ModelMessage, placed: Sequence[_PlacedComment]
) -> ModelMessage:
    """Mutate pydantic-ai's message to carry the comments, and hand back the
    SAME object - identity is what stops `adopt` mounting a second copy."""
    canonical.parts = _splice_comments(placed, canonical.parts)
    return canonical


def _splice_comments(
    placed: Sequence[_PlacedComment], canonical: Sequence[Any]
) -> list[Any]:
    """Replay each comment into `canonical` behind the tool return it followed.

    Anchored on `tool_call_id`, never on list position: the canonical parts are
    authoritative and may hold a part we never saw (a retry, a repair), which
    would shift every index. A comment whose anchor is missing from those parts
    goes at the end rather than being dropped."""
    after: dict[str | None, list[Any]] = {}
    for comment in placed:
        after.setdefault(comment.after, []).append(UserPromptPart(content=comment.text))

    spliced: list[Any] = list(after.pop(None, ()))
    for part in canonical:
        spliced.append(part)
        if isinstance(part, ToolReturnPart):
            spliced.extend(after.pop(part.tool_call_id, ()))
    for orphaned in after.values():
        spliced.extend(orphaned)
    return spliced


async def _assemble_tool_returns(
    conversation: Conversation,
    node: Any,
    run_ctx: Any,
    inbox: UserMessageQueue,
    placed: list[_PlacedComment],
) -> None:
    """Grow one ModelRequest in the Conversation as each tool return lands, so
    the transcript shows a result the moment its tool finishes rather than all
    of them at once when the node ends.

    NOTE: per-tool liveness is not a documented pydantic-ai guarantee - it holds
    under the sequential execution run_turn_with_retry already forces (the
    consent UI is single-flight), and with tools that genuinely overlap the same
    events arrive buffered and out of completion order. If it ever stops
    holding, ordering degrades quietly to "every result, then every comment", so
    it is pinned by test_call_tools_node_streams_a_result_event_per_tool.

    A comment typed while a tool ran is drained in BEHIND that tool's result,
    and `placed` records WHICH result at the moment it happens - not
    reconstructed later from part order or from timestamps.
    `UserPromptPart.timestamp` is stamped when the part is built, not when the
    user hit Enter, so a sort would order by the wrong clock; the boundary has
    no clock at all. That record is what the canonical message is rebuilt from,
    which leaves the entry below purely a display concern."""
    parts: list[Any] = []
    async with node.stream(run_ctx) as stream:
        async for event in stream:
            if not isinstance(event, FunctionToolResultEvent):
                continue
            parts.append(event.part)
            for comment in _drain_user_comments(inbox):
                placed.append(_PlacedComment(comment, after=event.part.tool_call_id))
                parts.append(UserPromptPart(content=comment))
            message = ModelRequest(parts=list(parts))
            if conversation.assembling:
                await conversation.assembly_updated(message)
            else:
                await conversation.begin_assembly(message)


async def _hold_for_autonomy(deps: SolveigContext, inbox: UserMessageQueue) -> str:
    """Block until the user grants an explicit go-ahead, returning whatever
    they sent with it.

    Becomes the `before_model_request` gate: "ask before sending this to the
    assistant". Split from the comment drain below because the two are headed
    for different hooks - the gate to `before_model_request`, the drain to the
    per-tool boundary in the event stream."""
    await deps.interface.set_status("Awaiting confirmation to continue")
    comment = await inbox.get()
    await deps.interface.set_status(None)
    return comment


def _drain_user_comments(inbox: UserMessageQueue) -> list[str]:
    """Take everything typed since the last drain, oldest first.

    Non-blocking by construction: an empty inbox yields an empty list, never a
    wait. The caller decides where the comments go."""
    comments: list[str] = []
    while True:
        try:
            comments.append(inbox.get_nowait())
        except asyncio.QueueEmpty:
            return comments


def build_run_capability(
    reconciler: _Reconciler, inbox: UserMessageQueue
) -> Hooks[SolveigContext]:
    """Per-RUN capability: the two concerns that need this run's conversation
    state. Passed to `agent.iter(capabilities=[...])`, which merges it with the
    Agent's own — so neither `SolveigContext` nor `build_agent` has to grow a
    field for state that only exists once a run is under way.

    `before_model_request` is the autonomy gate's real home: "ask before sending
    this to the assistant". The old gate sat on the tool-round boundary and had
    to INFER that a request was coming (a node that ran tool calls is always
    followed by one); here it simply holds the request. It also fires on a step
    that ran no tools, which the inference could never cover.

    `after_node_run` fires only because the loop drives with `run.next()`; bare
    `async for` uses the graph's internal iteration and skips every node hook.
    """
    hooks: Hooks[SolveigContext] = Hooks()

    @hooks.on.before_model_request
    async def hold_and_deliver(
        ctx: RunContext[SolveigContext], request_context: Any
    ) -> Any:
        comments: list[str] = []
        # Every step but the run's first - the user typed that prompt, there is
        # nothing to confirm. `run_step` is already incremented when this fires.
        if ctx.deps.config.disable_autonomy and ctx.run_step > 1:
            comments.append(await _hold_for_autonomy(ctx.deps, inbox))
        # Always-on drain: anything typed while tools ran, or while the gate was
        # blocked, rides out with this request in any autonomy mode.
        comments.extend(_drain_user_comments(inbox))
        if comments:
            message = ModelRequest(
                parts=[UserPromptPart(content=comment) for comment in comments]
            )
            # Both lists, mirroring pydantic-ai's own PendingMessageDrainCapability:
            # `request_context.messages` is what this step sends, `ctx.messages`
            # is the history that outlives it. Appending to only one either
            # loses the comment after this step or hides it from the model now.
            request_context.messages.append(message)
            ctx.messages.append(message)
        return request_context

    @hooks.on.after_node_run
    async def reconcile(ctx: RunContext[SolveigContext], *, node: Any, result: Any):
        await reconciler.sync(ctx.messages)
        return result

    return hooks


async def run_turn(
    agent: Agent[SolveigContext, str],
    conversation: Conversation,
    deps: SolveigContext,
    prompt: str,
    inbox: UserMessageQueue,
) -> None:
    """Drive one run. pydantic-ai is the engine (model I/O, tool schemas + tool
    execution, consent via the tool_execute capability) and now also owns the
    lifecycle: reconciliation and the autonomy gate are hooks
    (`build_run_capability`), not lines here. What is left is the one thing no
    hook can express - streaming a response into a live Conversation entry with
    the READER cancellable.

    Driven by `run.next()`, not `async for`. Bare iteration uses the graph's
    internal stepping, which fires no node hooks at all; `next()` runs the full
    `before_node_run` -> `wrap_node_run` -> `after_node_run` lifecycle, which is
    what lets reconciliation live in a hook. (`before_node_run` therefore fires
    AFTER a streamed node was consumed here. Nothing registers it - the
    framework's own `run_stream` has the same ordering and reaches for a private
    method to avoid it.)

    The user's prompt is appended up front so it renders instantly (optimistic
    echo) rather than only when the run surfaces it. pydantic-ai creates its own
    equal-content request object for the prompt during the run; `_Reconciler`
    folds that into the echo's id so `adopt` never mounts a duplicate.
    Everything else adopts by object identity, and a finally syncs once more so
    a mid-run cancel commits whatever completed (spec §8)."""
    echo_id = await conversation.append(
        ModelRequest(parts=[UserPromptPart(content=prompt)])
    )
    history = list(conversation.messages[:-1])  # everything before the echo
    reconciler = _Reconciler(conversation, echo_id, anchor=len(history))

    async with agent.iter(
        prompt,
        message_history=history,
        usage=conversation.usage,
        deps=deps,
        capabilities=[build_run_capability(reconciler, inbox)],
    ) as run:

        async def sync() -> None:
            await reconciler.sync(run.all_messages())

        try:
            node = run.next_node
            while not isinstance(node, End):
                if deps.config.interface.stream and Agent.is_model_request_node(node):
                    try:
                        async with _thinking(
                            deps.interface,
                            _stream_response(conversation, node, run.ctx, sync),
                            deps.config.api.timeout,
                        ) as task:
                            await task
                    finally:
                        # Reconcile the in-flight snapshot with pydantic-ai's own
                        # response object under the same id, so neither the outer
                        # finally: sync() nor the CallToolsNode branch mounts a
                        # second copy. On a mid-stream cancel pydantic-ai has
                        # already appended its (partial) response to all_messages
                        # - fold it in by identity here; the no-op-when-absent
                        # guard leaves the normal path to finalize at the tool
                        # boundary as before.
                        finished = run.all_messages()
                        if finished and isinstance(finished[-1], ModelResponse):
                            await conversation.finalize_stream(finished[-1])

                elif Agent.is_call_tools_node(node):
                    # Swap the streamed (throwaway) object for pydantic-ai's
                    # canonical response under the same id, so adopt won't
                    # re-append it. No-op when streaming is off. The reactive
                    # transcript renders this response (text/reasoning) itself
                    # when adopt appends it - no imperative display here; the
                    # tool groups then render live inside the tool_execute hook.
                    await conversation.finalize_stream(node.model_response)
                    await sync()
                    # Consuming the node's stream is what EXECUTES its tools, so
                    # this replaces the advance rather than preceding it - the
                    # `run.next()` below then finds the work already done and
                    # just fires the node hooks and returns the next node.
                    await _assemble_tool_returns(
                        conversation, node, run.ctx, inbox, reconciler.placed
                    )

                # Advancing fires the node hooks, so reconciliation happens on
                # the way out of every node without a call here.
                node = await run.next(node)
        finally:
            await sync()


async def run_turn_with_retry(
    config: SolveigConfig,
    client: Client,
    interface: SolveigInterface,
    conversation: Conversation,
    system_prompt: str,
    prompt: str,
    inbox: UserMessageQueue,
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

        agent = build_agent(config, client, system_prompt, model=model)
        deps = SolveigContext(config=config, interface=interface)
        try:
            with Agent.parallel_tool_call_execution_mode("sequential"):
                await run_turn(agent, conversation, deps, prompt, inbox)
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


def build_tool_execution_capability() -> Hooks[SolveigContext]:
    """Per-tool-call capability: opens each call's collapsible group, runs the
    plugin `@before_tool`/`@after_tool` hooks, and renders the `ToolResult` into a
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
    `run_tool_and_hooks` - `run_untyped_tool` (also in orchestration.py) gives
    it the same group/approve/display treatment generically, since there's no
    typed schema to build a tool-specific header or decline message from.

    Stateless: `config`/`interface` come from `ctx.deps` and the hook
    registries are read live at call time, so a plugin rescan or
    `tools.<name>.enabled` toggle takes effect on the next call.
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

        # The ONE execution entrypoint for every tool call (typed and MCP):
        # cancellable here, so Esc kills a network call (MCP) or a tool body
        # alike. A consent PROMPT inside the body registers itself as the
        # latest task (ask_* -> _active_tasks), so Esc during a prompt still
        # hits the prompt (decline via UserCancel) rather than the body.
        try:
            async with interface.with_cancellable(
                _dispatch(instance, config, interface, call, args, handler),
                status="Executing",
            ) as task:
                result = await task
        except (PluginException, ToolDisabledError) as e:
            raise ModelRetry(str(e)) from e

        if isinstance(result, ToolResult):
            return result.to_tool_return()
        return result

    return hooks


async def _dispatch(
    instance: Any,
    config: SolveigConfig,
    interface: SolveigInterface,
    call: ToolCallPart,
    args: dict[str, Any],
    handler: Any,
) -> Any:
    """Route one tool call to its execution seam: a typed BaseTool through
    `run_tool_and_hooks`, anything else (MCP, plain-function plugin) through
    `run_untyped_tool`. Exists so the capability can wrap BOTH branches in
    one with_cancellable - the single entrypoint all tool execution shares."""
    if instance is None:
        return await run_untyped_tool(config, interface, call, args, handler)
    return await run_tool_and_hooks(instance, config, interface)
