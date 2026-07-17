import uuid

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    UserPromptPart,
)

from solveig.conversation import Conversation, ConversationObserver

pytestmark = pytest.mark.anyio


class SpyObserver:
    """Records observer callbacks in call order for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def message_added(self, message_id: str) -> None:
        self.events.append(("added", message_id))

    async def message_updated(self, message_id: str) -> None:
        self.events.append(("updated", message_id))

    async def truncated_from(self, message_id: str) -> None:
        self.events.append(("truncated", message_id))


async def test_append_assigns_uuid_id_notifies_and_orders():
    conv = Conversation()
    spy = SpyObserver()
    conv.subscribe(spy)

    m1 = ModelRequest(parts=[UserPromptPart(content="hello")])
    m2 = ModelResponse(parts=[TextPart(content="hi")])

    id1 = await conv.append(m1)
    id2 = await conv.append(m2)

    # ids are distinct, string, valid uuid4
    assert id1 != id2
    assert uuid.UUID(id1).version == 4
    # ordered list view reflects insertion order
    assert conv.messages == (m1, m2)
    assert conv.ids == (id1, id2)
    # O(1) lookup by id
    assert conv.get(id1) is m1
    assert conv.get("nonexistent") is None
    # each append fired exactly one 'added' with its id, in order
    assert spy.events == [("added", id1), ("added", id2)]


async def test_edit_mutates_addressed_part_in_place_and_notifies():
    conv = Conversation()
    spy = SpyObserver()
    resp = ModelResponse(parts=[ThinkingPart(content="hmm"), TextPart(content="draft")])
    mid = await conv.append(resp)
    conv.subscribe(spy)  # subscribe after append so we only see the edit event

    await conv.edit(mid, 1, "final")

    assert conv.get(mid).parts[1].content == "final"
    assert conv.get(mid).parts[0].content == "hmm"  # sibling untouched
    assert spy.events == [("updated", mid)]


async def test_edit_rejects_non_editable_part():
    conv = Conversation()
    mid = await conv.append(ModelResponse(parts=[ToolCallPart(tool_name="x", args={})]))
    with pytest.raises(ValueError, match="not an editable part"):
        await conv.edit(mid, 0, "nope")


async def test_truncate_from_drops_target_and_following_and_notifies():
    conv = Conversation()
    a = await conv.append(ModelRequest(parts=[UserPromptPart(content="a")]))
    b = await conv.append(ModelResponse(parts=[TextPart(content="b")]))
    c = await conv.append(ModelRequest(parts=[UserPromptPart(content="c")]))
    spy = SpyObserver()
    conv.subscribe(spy)

    await conv.truncate_from(b)

    assert conv.ids == (a,)
    assert conv.get(b) is None and conv.get(c) is None
    assert spy.events == [("truncated", b)]


async def test_truncate_from_absent_id_is_noop_without_notify():
    conv = Conversation()
    a = await conv.append(ModelRequest(parts=[UserPromptPart(content="a")]))
    spy = SpyObserver()
    conv.subscribe(spy)

    await conv.truncate_from("does-not-exist")

    assert conv.ids == (a,)
    assert spy.events == []
