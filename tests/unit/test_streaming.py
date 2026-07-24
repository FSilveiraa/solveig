import asyncio

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets.function import FunctionToolset

from solveig.agent import build_agent, run_turn
from solveig.context import SolveigContext
from solveig.conversation import Conversation
from solveig.inbox import Inbox
from solveig.tools.available import AVAILABLE_TOOLS
from tests.mocks import DEFAULT_CONFIG, MockInterface, create_mock_model
from tests.mocks.reactive import RecordingTranscript

pytestmark = pytest.mark.anyio


def _deps(conv, *, stream=True, interface=None):
    config = DEFAULT_CONFIG.model_copy(
        update={"interface": DEFAULT_CONFIG.interface.model_copy(update={"stream": stream})}
    )
    return SolveigContext(config=config, interface=interface or MockInterface())


async def _chunks(messages, info):
    for chunk in ["Hel", "lo ", "world"]:
        yield chunk


async def test_single_response_streams_then_finalizes_without_duplicate():
    conv = Conversation()
    view = RecordingTranscript(conv)
    agent = Agent(FunctionModel(stream_function=_chunks))

    await run_turn(agent, conv, _deps(conv), "hi", Inbox())

    kinds = [type(m).__name__ for m in conv.messages]
    assert kinds == ["ModelRequest", "ModelResponse"]  # exactly one response, no dup
    assert conv.messages[-1].parts[0].content == "Hello world"

    resp_id = conv.ids[-1]
    # streamed: the response entry was re-rendered several times (bursts)
    rerenders = [i for k, i in view.events if k == "rerender" and i == resp_id]
    assert len(rerenders) >= 2
    # final materialized content is the assembled text
    assert view.mounted[resp_id] == ["Hello world"]


async def test_rerenders_show_growing_partial_content():
    """Each streamed rerender must reflect the tokens accumulated SO FAR, not a
    frozen snapshot captured at begin_stream (regression: stream.response builds
    a fresh immutable ModelResponse per access - it never mutates in place, so
    the entry must be re-snapshotted on every event)."""

    class ContentRecorder(RecordingTranscript):
        def __init__(self, conv):
            self.content_history: list[str] = []
            super().__init__(conv)

        async def rerender(self, message_id):
            await super().rerender(message_id)
            text = "".join(self.mounted[message_id])
            self.content_history.append(text)

    conv = Conversation()
    view = ContentRecorder(conv)
    agent = Agent(FunctionModel(stream_function=_chunks))

    await run_turn(agent, conv, _deps(conv), "hi", Inbox())

    # There must be a rerender showing partial content: more than nothing, but
    # not yet the whole "Hello world". A frozen snapshot never produces this.
    partials = [c for c in view.content_history if c and c != "Hello world"]
    assert partials, f"no partial content observed: {view.content_history}"
    # And the partials must strictly grow toward the final text.
    assert any(c.startswith("Hel") and len(c) < len("Hello world") for c in partials)


async def test_multi_round_streaming_preserves_order_and_no_duplicates():
    def echo(x: str) -> str:
        return x

    conv = Conversation()
    RecordingTranscript(conv)
    agent = Agent(TestModel(), toolsets=[FunctionToolset([echo])])

    await run_turn(agent, conv, _deps(conv), "go", Inbox())

    kinds = [type(m).__name__ for m in conv.messages]
    # request -> response(tool call) -> tool-return request -> response(text)
    assert kinds == ["ModelRequest", "ModelResponse", "ModelRequest", "ModelResponse"]
    assert len(conv.messages) == 4  # nothing duplicated across rounds


async def test_create_mock_model_streams_reasoning_and_text():
    """The demo/mock model must be stream-capable (regression: config.stream
    defaults on, and a function-only FunctionModel crashed run_turn's
    node.stream). It reconstructs reasoning + text as stream deltas."""
    from pydantic_ai.messages import ModelResponse, TextPart, ThinkingPart

    conv = Conversation()
    view = RecordingTranscript(conv)
    model = create_mock_model(
        ModelResponse(
            parts=[
                ThinkingPart(content="let me think"),
                TextPart(content="streamed answer"),
            ]
        )
    )
    agent = Agent(model)

    await run_turn(agent, conv, _deps(conv), "hi", Inbox())

    assert [type(m).__name__ for m in conv.messages] == [
        "ModelRequest",
        "ModelResponse",
    ]
    response = conv.messages[-1]
    assert any(
        isinstance(p, ThinkingPart) and p.content == "let me think"
        for p in response.parts
    )
    assert any(
        isinstance(p, TextPart) and p.content == "streamed answer"
        for p in response.parts
    )
    # streamed in bursts, not one shot
    assert sum(1 for k, _ in view.events if k == "rerender") >= 2


async def test_cancel_mid_stream_is_clean_and_leaves_one_partial():
    """Cancelling a streaming response (Esc/Ctrl+C) must raise a clean
    CancelledError (so run_turn_with_retry treats it as a cancel, not an API
    failure), keep the animation, and leave exactly ONE partial response entry -
    not a duplicate. Regression: the model_request hook used to wrap the parked
    request handler in with_cancellable; cancelling it tore the stream mid-read
    and left pydantic-ai's partial to be adopted alongside the streamed entry."""

    async def _slow(messages, info):
        for chunk in ["Rea", "son", "ing", " more"]:
            await asyncio.sleep(0.05)
            yield chunk

    conv = Conversation()
    view = RecordingTranscript(conv)
    interface = MockInterface()
    deps = _deps(conv, stream=True, interface=interface)
    AVAILABLE_TOOLS.rebuild(deps.config)
    agent = build_agent(
        deps.config, None, "sys", model=FunctionModel(stream_function=_slow)
    )

    turn = asyncio.create_task(run_turn(agent, conv, deps, "hi", Inbox()))

    # Cancel once streaming has actually started (a partial rerender landed).
    for _ in range(200):
        if any(k == "rerender" for k, _ in view.events):
            break
        await asyncio.sleep(0.01)
    assert interface.has_active_operations
    assert interface.cancel_active_operation()

    with pytest.raises(asyncio.CancelledError):
        await turn

    # Exactly one partial ModelResponse survives - no duplicate box.
    responses = [m for m in conv.messages if type(m).__name__ == "ModelResponse"]
    assert len(responses) == 1
    assert (
        responses[0].parts[0].content
        and responses[0].parts[0].content != "Reasoning more"
    )
    # The animation ran while streaming.
    assert any(s.get("status") == "Thinking" for s in interface.stats_updates)
