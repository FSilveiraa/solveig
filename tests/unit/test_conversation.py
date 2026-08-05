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
from pydantic_ai.usage import RunUsage

from solveig.session.conversation import Conversation

pytestmark = pytest.mark.anyio


class SpyObserver:
    """Records raw observer callbacks (event name + args) in call order.

    Implements the full `ConversationObserver` Protocol - not a subset - so a
    missing/renamed event method is a loud Type/AttributeError, not a silent
    silent passthrough. Tests the Conversation's own event contract precisely;
    `RecordingTranscript` (tests/mocks) models the display-side reduction.
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, ...]] = []

    async def message_added(self, message_id: str) -> None:
        self.events.append(("added", message_id))

    async def stream_began(self, message_id: str) -> None:
        self.events.append(("began", message_id))

    async def stream_updated(self, message_id: str) -> None:
        self.events.append(("stream_updated", message_id))

    async def stream_completed(self, message_id: str) -> None:
        self.events.append(("completed", message_id))

    async def message_edited(self, message_id: str) -> None:
        self.events.append(("edited", message_id))

    async def truncated_from(self, message_id: str) -> None:
        self.events.append(("truncated", message_id))

    async def branched_from(self, message_id: str, previous: Conversation) -> None:
        self.events.append(("branched", message_id, previous))

    async def conversation_loaded(self, previous: Conversation) -> None:
        self.events.append(("loaded",))


async def test_append_assigns_uuid_id_notifies_and_orders():
    conv = Conversation()
    spy = SpyObserver()
    conv.register_observer(spy)

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
    resp = ModelResponse(parts=[ThinkingPart(content="hmm"), TextPart(content="draft")])
    mid = await conv.append(resp)
    spy = SpyObserver()
    conv.register_observer(spy)  # register after append so we only see the edit

    await conv.edit(mid, 1, "final")

    assert conv.get(mid).parts[1].content == "final"
    assert conv.get(mid).parts[0].content == "hmm"  # sibling untouched
    assert spy.events == [("edited", mid)]


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
    conv.register_observer(spy)

    await conv.truncate_from(b)

    assert conv.ids == (a,)
    assert conv.get(b) is None and conv.get(c) is None
    assert spy.events == [("truncated", b)]


async def test_truncate_from_absent_id_is_noop_without_notify():
    conv = Conversation()
    a = await conv.append(ModelRequest(parts=[UserPromptPart(content="a")]))
    spy = SpyObserver()
    conv.register_observer(spy)

    await conv.truncate_from("does-not-exist")

    assert conv.ids == (a,)
    assert spy.events == []


async def test_branch_from_hands_observers_the_before():
    conv = Conversation()
    a = await conv.append(ModelRequest(parts=[UserPromptPart(content="a")]))
    b = await conv.append(ModelResponse(parts=[TextPart(content="b")]))
    c = await conv.append(ModelRequest(parts=[UserPromptPart(content="c")]))
    spy = SpyObserver()
    conv.register_observer(spy)

    await conv.branch_from(b)

    assert conv.ids == (a,)  # b and c rewound
    assert spy.events[0][:2] == ("branched", b)
    # the BEFORE handed to the observer still has the pre-rewind entries
    _name, _mid, previous = spy.events[0]
    assert previous is not None
    assert previous.ids == (a, b, c)


async def test_adopt_appends_only_new_messages_by_identity():
    conv = Conversation()
    spy = SpyObserver()
    conv.register_observer(spy)

    a = ModelRequest(parts=[UserPromptPart(content="a")])
    a_id = await conv.append(a)

    b = ModelResponse(parts=[TextPart(content="b")])
    c = ModelResponse(parts=[TextPart(content="c")])
    # a is already present (same object) -> kept; b, c are new -> appended
    await conv.adopt([a, b, c])

    assert conv.messages == (a, b, c)
    assert conv.get(a_id) is a  # id preserved, not re-appended
    assert spy.events.count(("added", a_id)) == 1  # a mounted once, at append
    assert len(conv.ids) == 3

    # adopting the same list again is a no-op (idempotent)
    before = tuple(conv.ids)
    await conv.adopt([a, b, c])
    assert tuple(conv.ids) == before


async def test_load_replaces_wholesale_and_fires_one_loaded_event():
    conv = Conversation()
    await conv.append(ModelRequest(parts=[UserPromptPart(content="old")]))
    spy = SpyObserver()
    conv.register_observer(spy)  # after append so we only see the load

    msgs = [
        ModelRequest(parts=[UserPromptPart(content="one")]),
        ModelResponse(parts=[TextPart(content="two")]),
    ]
    usage = RunUsage(input_tokens=5, output_tokens=7)
    await conv.load(msgs, usage)

    assert conv.messages == tuple(msgs)
    assert conv.usage is usage
    # A load is ONE conversation_loaded event - not a truncated + message_added
    # burst, so a display/persistence can tell a live add from a resume.
    assert spy.events == [("loaded",)]


async def test_streaming_lifecycle_updates_then_finalizes_without_duplicate():
    conv = Conversation()
    spy = SpyObserver()
    conv.register_observer(spy)

    # pydantic-ai hands a fresh immutable snapshot per token burst (stream.response
    # never mutates in place), so each update swaps in a new object under the id.
    sid = await conv.begin_stream(ModelResponse(parts=[TextPart(content="Hel")]))
    assert spy.events == [("began", sid)]

    await conv.stream_updated(ModelResponse(parts=[TextPart(content="Hello")]))
    assert conv.get(sid).parts[0].content == "Hello"
    await conv.stream_updated(ModelResponse(parts=[TextPart(content="Hello world")]))
    assert conv.get(sid).parts[0].content == "Hello world"
    assert spy.events == [("began", sid), ("stream_updated", sid), ("stream_updated", sid)]

    # finalize with the canonical (different) object of equal content
    final = ModelResponse(parts=[TextPart(content="Hello world")])
    await conv.finalize_stream(final)
    assert spy.events[-1] == ("completed", sid)
    assert conv.get(sid) is final
    assert conv._inflight_id is None

    # adopt over the authoritative list must NOT re-append the finalized response
    await conv.adopt([final])
    assert conv.messages == (final,)
    assert len(conv.ids) == 1


async def test_stream_updated_and_finalize_are_noops_when_not_streaming():
    conv = Conversation()
    spy = SpyObserver()
    conv.register_observer(spy)
    await conv.stream_updated(ModelResponse(parts=[]))  # no inflight
    await conv.finalize_stream(ModelResponse(parts=[]))
    assert spy.events == []
    assert conv.messages == ()


async def test_assembly_trio_mirrors_streaming():
    """An entry assembled part-by-part (growing ModelRequest) uses the same
    observer events as a streamed response - began/updated/completed."""
    conv = Conversation()
    spy = SpyObserver()
    conv.register_observer(spy)

    aid = await conv.begin_assembly(ModelRequest(parts=[UserPromptPart(content="u")]))
    assert spy.events == [("began", aid)]
    assert conv.assembling is True

    await conv.assembly_updated(
        ModelRequest(
            parts=[UserPromptPart(content="u"), ToolCallPart(tool_name="t", args={})]
        )
    )
    assert spy.events[-1] == ("stream_updated", aid)
    assert len(conv.get(aid).parts) == 2

    canonical = ModelRequest(
        parts=[UserPromptPart(content="u"), ToolCallPart(tool_name="t", args={})]
    )
    await conv.finalize_assembly(canonical)
    assert spy.events[-1] == ("completed", aid)
    assert conv.get(aid) is canonical
    assert conv.assembling is False
