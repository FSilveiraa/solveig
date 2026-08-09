import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.test import TestModel

from solveig.agent import run_turn
from solveig.context import SolveigContext
from solveig.session.conversation import Conversation
from solveig.user_message_queue import UserMessageQueue
from tests.mocks import DEFAULT_CONFIG, MockInterface
from tests.mocks.reactive import RecordingTranscript

pytestmark = pytest.mark.anyio


def _deps(interface, conversation):
    return SolveigContext(config=DEFAULT_CONFIG, interface=interface)


async def test_run_turn_adopts_messages_into_conversation():
    conv = Conversation()
    view = RecordingTranscript(conv)  # observes reactively
    agent = Agent(TestModel())  # no consent tools -> single request/response

    await run_turn(agent, conv, _deps(MockInterface(), conv), "hello", UserMessageQueue())

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
    await run_turn(agent, conv, _deps(MockInterface(), conv), "again", UserMessageQueue())

    # prior ids unchanged (identity-preserved), new ones appended after
    assert list(conv.ids)[: len(before_ids)] == before_ids
    assert len(conv.ids) == len(before_ids) + 2  # new user prompt + response


async def test_pydantic_ai_preserves_message_history_object_identity():
    """Load-bearing invariant for Conversation.adopt(), which dedupes by id():
    pydantic-ai must hand back the SAME message objects we passed as
    message_history. A future version that deep-copied the history would make
    adopt() mount duplicates - this pins the assumption so it fails loudly."""
    history = [
        ModelRequest(parts=[UserPromptPart(content="earlier")]),
        ModelResponse(parts=[TextPart(content="reply")]),
    ]
    agent = Agent(TestModel())
    async with agent.iter("next", message_history=history) as run:
        async for _ in run:
            pass
        all_messages = run.all_messages()

    # The run's history prefix must be the very objects we handed in (identity).
    assert all_messages[0] is history[0]
    assert all_messages[1] is history[1]
