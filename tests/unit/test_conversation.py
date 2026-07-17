import uuid

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

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
