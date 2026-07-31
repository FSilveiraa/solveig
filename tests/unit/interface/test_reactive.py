import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from solveig.session.conversation import Conversation
from tests.mocks.reactive import RecordingTranscript

pytestmark = pytest.mark.anyio


async def test_append_mounts_presented_nodes():
    conv = Conversation()
    view = RecordingTranscript(conv)
    mid = await conv.append(ModelRequest(parts=[UserPromptPart(content="hi")]))
    assert view.mounted == {mid: ["hi"]}
    assert view.events == [("mount", mid)]


async def test_edit_rerenders_that_message_only():
    conv = Conversation()
    view = RecordingTranscript(conv)
    a = await conv.append(ModelResponse(parts=[TextPart(content="one")]))
    b = await conv.append(ModelResponse(parts=[TextPart(content="two")]))
    await conv.edit(a, 0, "ONE")
    assert view.mounted[a] == ["ONE"]
    assert view.mounted[b] == ["two"]
    assert view.events[-1] == ("rerender", a)


async def test_truncate_removes_from_id_onward_in_order():
    conv = Conversation()
    view = RecordingTranscript(conv)
    a = await conv.append(ModelResponse(parts=[TextPart(content="a")]))
    b = await conv.append(ModelResponse(parts=[TextPart(content="b")]))
    c = await conv.append(ModelResponse(parts=[TextPart(content="c")]))
    await conv.truncate_from(b)
    assert list(view.mounted.keys()) == [a]
    assert view.events[-1] == ("remove", (b, c))


async def test_truncate_unknown_id_is_noop():
    conv = Conversation()
    view = RecordingTranscript(conv)
    await conv.append(ModelResponse(parts=[TextPart(content="a")]))
    before = list(view.events)
    await conv.truncate_from("no-such-id")
    assert view.events == before
