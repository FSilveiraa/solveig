import pytest
from pydantic_ai import Agent
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets.function import FunctionToolset

from solveig.agent import run_turn
from solveig.context import SolveigContext
from solveig.conversation import Conversation
from solveig.interface.render import Markdown
from solveig.sessions.manager import SessionManager
from tests.mocks import DEFAULT_CONFIG, MockInterface, create_mock_model
from tests.mocks.reactive import RecordingTranscript

pytestmark = pytest.mark.anyio


def _deps(conv, *, stream=True):
    config = DEFAULT_CONFIG.with_(stream=stream)
    return SolveigContext(
        config=config,
        interface=MockInterface(),
        conversation=conv,
        session_manager=SessionManager(config=config),
    )


async def _chunks(messages, info):
    for chunk in ["Hel", "lo ", "world"]:
        yield chunk


async def test_single_response_streams_then_finalizes_without_duplicate():
    conv = Conversation()
    view = RecordingTranscript(conv)
    agent = Agent(FunctionModel(stream_function=_chunks))

    await run_turn(agent, conv, _deps(conv), "hi")

    kinds = [type(m).__name__ for m in conv.messages]
    assert kinds == ["ModelRequest", "ModelResponse"]  # exactly one response, no dup
    assert conv.messages[-1].parts[0].content == "Hello world"

    resp_id = conv.ids[-1]
    # streamed: the response entry was re-rendered several times (bursts)
    rerenders = [i for k, i in view.events if k == "rerender" and i == resp_id]
    assert len(rerenders) >= 2
    # final materialized content is the assembled text
    assert view.mounted[resp_id] == [Markdown("Hello world")]


async def test_multi_round_streaming_preserves_order_and_no_duplicates():
    def echo(x: str) -> str:
        return x

    conv = Conversation()
    RecordingTranscript(conv)
    agent = Agent(TestModel(), toolsets=[FunctionToolset([echo])])

    await run_turn(agent, conv, _deps(conv), "go")

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

    await run_turn(agent, conv, _deps(conv), "hi")

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
