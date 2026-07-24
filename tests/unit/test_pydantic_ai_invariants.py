"""The pydantic-ai behaviors solveig leans on, pinned as executable alarms.

This file IS the dependency upgrade gate (pyproject: ``pydantic-ai>=2.17,<3``).
On ANY pydantic-ai bump, run this file first. The pins are behavioral - they
run against whichever pydantic-ai is installed and fail loudly on drift - so a
mismatched dev env (different venv, stale lockfile) is caught here, not in
production. Audited against v2.17.0; see
``ignore/project-logs/2026-07-24-02-03-post-migration-followups.md`` §P2.

Tier labels say how to react to a failure (pydantic-ai's version policy only
promises no *intentional* breakage of documented behavior in V2 minors):

- Tier A (documented):        the framework broke its own promise - file upstream.
- Tier B (contract-adjacent): implied by documented behavior - file upstream,
                              expect "undocumented" pushback; start decoupling.
- Tier C (undocumented):      may change ANY release with no changelog
                              obligation. Stop, read the new source, adapt
                              solveig. This is expected to fire eventually.

Per-invariant guard triage (what run_turn already defends in code vs. what
only this file can catch): #1 identity gets a cheap length-assert at the
adopt site; #2 anchor has a content-verify + search fallback in run_turn -
this pin is the alarm that fires if the fallback ever runs; #3 cancel-commit
is additionally de-risked by run_turn finalizing from its own stream snapshot;
#4 and #5 are unguardable (snapshot freshness is unverifiable at runtime, a
missing future request is only detectable by waiting) - pin + doc only.
"""

import asyncio

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

pytestmark = pytest.mark.anyio


def _tool_calling_model() -> FunctionModel:
    """One tool call on the first request, text once the tool result comes back."""

    def respond(
        messages: list[ModelRequest | ModelResponse], info: AgentInfo
    ) -> ModelResponse:
        has_tool_return = any(
            isinstance(m, ModelRequest)
            and any(isinstance(p, ToolReturnPart) for p in m.parts)
            for m in messages
        )
        if not has_tool_return:
            return ModelResponse(parts=[ToolCallPart(tool_name="noop", args={})])
        return ModelResponse(parts=[TextPart(content="done")])

    return FunctionModel(respond)


async def test_1_history_element_identity():
    """TIER B (contract-adjacent): run_turn's adopt() dedupes by id(); pydantic-ai
    must hand back the SAME message objects passed as message_history (the
    container itself is copied - elements are shared). Mechanism:
    agent/__init__.py GraphAgentState(message_history=list(message_history))."""
    history = [
        ModelRequest(parts=[UserPromptPart(content="earlier")]),
        ModelResponse(parts=[TextPart(content="reply")]),
    ]
    agent = Agent(TestModel())
    async with agent.iter("next", message_history=history) as run:
        async for _ in run:
            pass
        all_messages = run.all_messages()

    assert all_messages[0] is history[0]
    assert all_messages[1] is history[1]


async def test_2_prompt_request_lands_at_anchor():
    """TIER C (UNDOCUMENTED coincidence): run_turn computes
    ``anchor = len(history)`` and reidentifies its optimistic echo against
    ``messages[anchor]`` - i.e. pydantic-ai's own request object for the prompt
    must land exactly at that index. Mechanism: UserPromptNode builds the
    request, ModelRequestNode appends it (_agent_graph.py). Nothing documents
    the position; a ReinjectSystemPrompt-style head-insertion is the realistic
    breaker. run_turn has a search-by-content fallback - if this pin fails,
    that fallback just started earning its keep."""
    history = [
        ModelRequest(parts=[UserPromptPart(content="earlier")]),
        ModelResponse(parts=[TextPart(content="reply")]),
    ]
    agent = Agent(TestModel())
    async with agent.iter("next", message_history=history) as run:
        async for _ in run:
            pass
        all_messages = run.all_messages()

    anchor = len(history)
    assert len(all_messages) > anchor
    prompt_request = all_messages[anchor]
    assert isinstance(prompt_request, ModelRequest)
    assert any(
        isinstance(part, UserPromptPart) and part.content == "next"
        for part in prompt_request.parts
    )


async def test_3_cancelled_stream_commits_partial_response():
    """TIER A (documented - V2 changelog breaking-change entry): cancelling a
    streamed response mid-flight leaves the partial response appended to
    all_messages(), stamped state='interrupted'. run_turn's streaming finally
    folds that object in via finalize_stream(all_messages()[-1]). Mechanism:
    _agent_graph.py stream handler finally-block ("so all_messages() include
    what was streamed")."""
    gate = asyncio.Event()
    captured: dict[str, object] = {}

    async def stream_forever(
        messages: list[ModelRequest | ModelResponse], info: AgentInfo
    ):
        yield "partial-"
        await gate.wait()  # hangs until the reader task is cancelled
        yield "rest"  # pragma: no cover - never reached

    async def consume() -> None:
        agent = Agent(FunctionModel(stream_function=stream_forever))
        async with agent.iter("hi") as run:
            captured["run"] = run
            async for node in run:
                if Agent.is_model_request_node(node):
                    async with node.stream(run.ctx) as stream:
                        async for _ in stream:
                            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)  # let the first chunk land before cancelling
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The cancel unwound the stream inside the graph's finally, which commits
    # the partial BEFORE the task actually dies - so the captured run's
    # all_messages() must already hold it.
    all_messages = captured["run"].all_messages()
    partial = all_messages[-1]
    assert isinstance(partial, ModelResponse)
    assert partial.state == "interrupted"
    text = "".join(part.content for part in partial.parts if isinstance(part, TextPart))
    assert "partial-" in text


async def test_4_stream_response_is_fresh_snapshot_per_access():
    """TIER B (contract-adjacent - property docstring: "Get the current state of
    the response"; freshness itself is not named): each access of
    stream.response builds a NEW ModelResponse (and new parts list) reflecting
    the stream so far; earlier snapshots must NOT mutate as more stream events
    arrive. conversation.begin_stream(stream.response) stores the object and
    later stream_updated(stream.response) swaps it - mutate-in-place would
    corrupt the already-rendered earlier state. Mechanism: result.py
    AgentStream.response -> StreamedResponse.get() -> _parts_manager.get_parts()
    (new list). UNGUARDABLE at runtime - this pin is the only alarm."""
    chunks = iter(["a", "b"])
    streamed = asyncio.Event()

    async def two_chunks(messages: list[ModelRequest | ModelResponse], info: AgentInfo):
        yield next(chunks)
        streamed.set()
        yield next(chunks)

    agent = Agent(FunctionModel(stream_function=two_chunks))
    async with agent.iter("hi") as run:
        async for node in run:
            if Agent.is_model_request_node(node):
                async with node.stream(run.ctx) as stream:
                    first = stream.response
                    async for _ in stream:
                        break  # consumed exactly one chunk
                    second = stream.response

    assert first is not second
    first_text = "".join(p.content for p in first.parts if isinstance(p, TextPart))
    second_text = "".join(p.content for p in second.parts if isinstance(p, TextPart))
    assert first_text != second_text, "snapshot must not mutate as the stream advances"
    assert second_text.startswith(first_text)


async def test_5_tool_round_is_followed_by_model_request():
    """TIER B (documented-ish - CallToolsNode class docstring: the node "decides
    whether to end the run or make a new request"; the exact edge isn't drawn in
    prose): a node that ran tool calls is ALWAYS followed by another
    ModelRequestNode. run_turn's CallToolsNode branch relies on this for the
    autonomy gate ("more is coming") with no lookahead. Mechanism:
    _agent_graph.py _handle_tool_calls sets _next_node = ModelRequestNode(...)
    on every path that lacks a final result. UNGUARDABLE (liveness - a missing
    future request is only detectable by waiting)."""
    agent = Agent(_tool_calling_model())

    @agent.tool_plain
    def noop() -> str:
        return "ok"

    tool_round_indices: list[int] = []
    node_sequence: list[str] = []
    async with agent.iter("use the tool") as run:
        async for node in run:
            node_sequence.append(type(node).__name__)
            if Agent.is_call_tools_node(node) and any(
                isinstance(part, ToolCallPart) for part in node.model_response.parts
            ):
                tool_round_indices.append(len(node_sequence) - 1)

    assert tool_round_indices, "the model must actually have run a tool round"
    # run.next_node mirrors the CURRENT node during iteration (no lookahead -
    # solveig's run_turn notes this), so the successor is observed by
    # iterating: a CallToolsNode whose response CARRIED tool calls must be
    # followed by a ModelRequestNode. (A no-tool-call CallToolsNode is the
    # terminal node and legitimately goes to End - that's the run ending.)
    for i in tool_round_indices:
        assert i + 1 < len(node_sequence), "tool round must not end the run"
        assert node_sequence[i + 1] == "ModelRequestNode"
