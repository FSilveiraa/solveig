import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.test import TestModel

from solveig.agent import run_turn
from solveig.context import SolveigContext
from solveig.conversation import Conversation
from solveig.sessions.manager import SessionManager
from tests.mocks import DEFAULT_CONFIG, MockInterface
from tests.mocks.reactive import RecordingTranscript

pytestmark = pytest.mark.anyio


def _deps(interface, conversation):
    return SolveigContext(
        config=DEFAULT_CONFIG,
        interface=interface,
        conversation=conversation,
        session_manager=SessionManager(config=DEFAULT_CONFIG),
    )


async def test_run_turn_adopts_messages_into_conversation():
    conv = Conversation()
    view = RecordingTranscript(conv)  # observes reactively
    agent = Agent(TestModel())  # no consent tools -> single request/response

    await run_turn(agent, conv, _deps(MockInterface(), conv), "hello")

    # user prompt + assistant response landed as reactive entries
    kinds = [type(m).__name__ for m in conv.messages]
    assert kinds == ["ModelRequest", "ModelResponse"]
    # everything that landed in the conversation was mounted reactively
    assert list(view.mounted.keys()) == list(conv.ids)


async def test_run_turn_preserves_prior_history_ids():
    conv = Conversation()
    # a prior committed turn
    await conv.append(ModelRequest(parts=[UserPromptPart(content="prior")]))
    await conv.append(ModelResponse(parts=[TextPart(content="prior-answer")]))
    before_ids = list(conv.ids)

    agent = Agent(TestModel())
    await run_turn(agent, conv, _deps(MockInterface(), conv), "again")

    # prior ids unchanged (identity-preserved), new ones appended after
    assert list(conv.ids)[: len(before_ids)] == before_ids
    assert len(conv.ids) == len(before_ids) + 2  # new user prompt + response
