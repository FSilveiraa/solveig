"""A user comment typed while a tool runs must reach the model IN PLACE —
between the result of the tool that was running and the next one — not appended
after every tool return.

Position is recorded at the boundary as each tool finishes, never reconstructed
afterwards by sorting timestamps: `UserPromptPart.timestamp` is stamped when the
part is built, not when the user pressed Enter, so a sort would order by the
wrong clock.
"""

import asyncio

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from solveig.agent import build_agent, run_turn
from solveig.context import SolveigContext
from solveig.session.conversation import Conversation
from solveig.user_message_queue import UserMessageQueue
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio


async def _two_tools_then_text(
    messages: list[ModelMessage], info: AgentInfo
) -> ModelResponse:
    if not any(isinstance(m, ModelResponse) for m in messages):
        return ModelResponse(
            parts=[
                ToolCallPart("slow", {"n": 1}, tool_call_id="c1"),
                ToolCallPart("slow", {"n": 2}, tool_call_id="c2"),
            ]
        )
    return ModelResponse(parts=[TextPart("done")])


def _config(**overrides):
    config = DEFAULT_CONFIG.model_copy(deep=True)
    config.interface.stream = False
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


async def _run(*, comment_after: int | None, sequential: bool = True):
    """Drive one run where `slow` queues a comment after tool `comment_after`."""
    config = _config()
    conversation = Conversation()
    inbox = UserMessageQueue()
    agent = build_agent(
        config, client=None, system_prompt="sys",
        model=FunctionModel(_two_tools_then_text),
    )

    @agent.tool_plain
    async def slow(n: int) -> str:
        if n == comment_after:
            inbox.put_nowait("how much longer?")
        return f"result {n}"

    deps = SolveigContext(config=config, interface=MockInterface(choices=[0] * 10))
    if sequential:
        with Agent.parallel_tool_call_execution_mode("sequential"):
            await run_turn(agent, conversation, deps, "go", inbox)
    else:
        await run_turn(agent, conversation, deps, "go", inbox)
    return conversation


def _tool_return_message(conversation: Conversation) -> ModelRequest:
    for message in conversation.messages:
        if isinstance(message, ModelRequest) and any(
            isinstance(part, ToolReturnPart) for part in message.parts
        ):
            return message
    raise AssertionError("no tool-return message in the conversation")


def _shape(message: ModelRequest) -> list[str]:
    return [
        f"{type(part).__name__}:{part.content}"
        for part in message.parts
        if isinstance(part, ToolReturnPart | UserPromptPart)
    ]


async def test_comment_lands_between_the_tool_results_it_was_typed_between():
    conversation = await _run(comment_after=1)

    assert _shape(_tool_return_message(conversation)) == [
        "ToolReturnPart:result 1",
        "UserPromptPart:how much longer?",
        "ToolReturnPart:result 2",
    ]


async def test_comment_after_the_last_tool_lands_at_the_end():
    conversation = await _run(comment_after=2)

    assert _shape(_tool_return_message(conversation)) == [
        "ToolReturnPart:result 1",
        "ToolReturnPart:result 2",
        "UserPromptPart:how much longer?",
    ]


async def test_tool_returns_are_one_message_not_duplicated():
    """The entry assembled as tools finished and pydantic-ai's canonical one are
    the same message built twice. Reconciliation must leave exactly one — adopt
    matches by object identity, so a copy would mount every tool return again."""
    conversation = await _run(comment_after=1)

    tool_return_messages = [
        message
        for message in conversation.messages
        if isinstance(message, ModelRequest)
        and any(isinstance(part, ToolReturnPart) for part in message.parts)
    ]
    assert len(tool_return_messages) == 1
    assert [type(m).__name__ for m in conversation.messages] == [
        "ModelRequest",
        "ModelResponse",
        "ModelRequest",
        "ModelResponse",
    ]


async def test_no_comment_leaves_the_canonical_parts_untouched():
    conversation = await _run(comment_after=None)

    assert _shape(_tool_return_message(conversation)) == [
        "ToolReturnPart:result 1",
        "ToolReturnPart:result 2",
    ]


async def test_comment_on_a_step_that_ran_no_tools_still_reaches_the_model():
    """The other drain site. A comment can arrive when there is no tool
    boundary to place it behind — a step whose response was pure text, or one
    typed after the last tool already finished. Those drain at
    `before_model_request` as their own ModelRequest instead.

    That is not a second ordering rule: with nothing to interleave between,
    "after everything" is the only chronological position, and pydantic-ai's
    `_merge_consecutive_messages` folds the adjacent requests into one on the
    wire anyway (tool returns first, which is what providers require)."""
    config = _config()
    conversation = Conversation()
    inbox = UserMessageQueue()
    inbox.put_nowait("no tools were harmed")

    async def text_only(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("nothing to do")])

    agent = build_agent(
        config, client=None, system_prompt="sys", model=FunctionModel(text_only)
    )
    deps = SolveigContext(config=config, interface=MockInterface(choices=[0] * 10))
    await run_turn(agent, conversation, deps, "go", inbox)

    prompts = [
        part.content
        for message in conversation.messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
    ]
    assert prompts == ["go", "no tools were harmed"]


async def test_comment_survives_a_cancelled_run():
    """A comment placed mid-tools must not be lost when the run is cancelled.

    It survives for a non-obvious reason, which is why this is pinned: the
    entry `_assemble_tool_returns` builds is a REAL conversation entry, not a
    staging buffer. A cancel only means pydantic-ai's canonical version never
    arrives to replace it, so the comment is already where it needs to be — and
    the next run sends `conversation.messages` as history.

    Nothing handles cancellation explicitly. If the assembled entry ever
    becomes provisional in a way that a cancel discards, this fails.
    """
    config = _config()
    conversation = Conversation()
    inbox = UserMessageQueue()
    interface = MockInterface(choices=[0] * 10)
    agent = build_agent(
        config, client=None, system_prompt="sys",
        model=FunctionModel(_two_tools_then_text),
    )

    @agent.tool_plain
    async def slow(n: int) -> str:
        if n == 1:
            inbox.put_nowait("how much longer?")
            return "result 1"
        await asyncio.sleep(30)  # cancelled below, never completes
        return "result 2"

    deps = SolveigContext(config=config, interface=interface)
    with Agent.parallel_tool_call_execution_mode("sequential"):
        turn = asyncio.create_task(run_turn(agent, conversation, deps, "go", inbox))
        for _ in range(300):
            await asyncio.sleep(0.01)
            if interface.get_active_tasks():
                break
        assert interface.cancel_task()
        with pytest.raises(asyncio.CancelledError):
            await turn

    assert _shape(_tool_return_message(conversation)) == [
        "ToolReturnPart:result 1",
        "UserPromptPart:how much longer?",
    ]


async def test_call_tools_node_streams_a_result_event_per_tool():
    """Pinned external invariant. Placing a comment between two tool results
    requires learning that tool 1 finished BEFORE tool 2 starts, and the only
    thing that reports it is `CallToolsNode.stream()` emitting one
    `FunctionToolResultEvent` per tool, carrying the real `ToolReturnPart`.

    Pinned rather than assumed because it is not a documented guarantee: it
    holds under sequential execution (which Solveig forces in
    `run_turn_with_retry` — the consent UI is single-flight), and with tools
    that genuinely overlap the same events arrive buffered and out of completion
    order. If a pydantic-ai version stops emitting them per tool, chronology
    degrades silently to "all results, then all comments" — this fails loudly
    instead.
    """
    import asyncio

    from pydantic_ai.messages import FunctionToolResultEvent
    from pydantic_graph import End

    agent = Agent(FunctionModel(_two_tools_then_text))
    order: list[str] = []

    @agent.tool_plain
    async def slow(n: int) -> str:
        await asyncio.sleep(0.02)
        order.append(f"finished {n}")
        return f"result {n}"

    with Agent.parallel_tool_call_execution_mode("sequential"):
        async with agent.iter("go") as run:
            node = run.next_node
            while not isinstance(node, End):
                if Agent.is_call_tools_node(node):
                    async with node.stream(run.ctx) as stream:
                        async for event in stream:
                            if isinstance(event, FunctionToolResultEvent):
                                order.append(f"event {event.part.content}")
                node = await run.next(node)

    # Each result is reported before the next tool runs, not batched at the end.
    assert order == [
        "finished 1",
        "event result 1",
        "finished 2",
        "event result 2",
    ]
