"""Conversation - the reactive single source of truth for the message history.

One insertion-ordered `dict[MessageId, ModelMessage]` IS both the ordered list
(`.values()`, handed to pydantic-ai as message_history) and the id-index
(`d[id]`, O(1) lookup/edit/address). There is no separate list+map to keep in
sync, so drift and leaks are structurally impossible. Every mutation is an
async method that updates the dict and then awaits registered observers.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from pydantic_ai.messages import (
    ModelMessage,
    TextPart,
    ThinkingPart,
    UserPromptPart,
)
from pydantic_ai.usage import RunUsage

MessageId = str

_EDITABLE_PARTS = (UserPromptPart, TextPart, ThinkingPart)


class ConversationObserver(Protocol):
    """Reactive subscriber. Core notifies; the observer reflects the change
    however it likes (a UI schedules a throttled redraw; persistence writes).

    Every change notifies — streamed tokens included. Batching, if an observer
    wants it, is that observer's own business and never encoded here.

    The events are split by WHAT HAPPENED, not by what any one observer needs,
    so nobody has to infer intent from a flag. There are no default
    implementations — a Protocol gives none, so an observer that ignores an
    event says so with an explicit no-op.

    `message_added` always means a COMPLETE message arrived (a user prompt, a
    tool call, a tool return, a non-streamed response). A streamed response is
    provisional until `stream_completed`, so it gets its own `stream_began`
    rather than being smuggled in as an add — otherwise persistence would write
    an empty response to an append-only file and be unable to retract it.
    """

    async def message_added(self, message_id: MessageId) -> None: ...
    async def stream_began(self, message_id: MessageId) -> None: ...
    async def stream_updated(self, message_id: MessageId) -> None: ...
    async def stream_completed(self, message_id: MessageId) -> None: ...
    async def message_edited(self, message_id: MessageId) -> None: ...
    async def truncated_from(self, message_id: MessageId) -> None: ...
    async def branched_from(
        self, message_id: MessageId, previous: Conversation
    ) -> None: ...
    async def conversation_loaded(self, previous: Conversation) -> None: ...


@dataclass
class Conversation:
    usage: RunUsage = field(default_factory=RunUsage)
    _entries: dict[MessageId, ModelMessage] = field(default_factory=dict)
    _observers: list[ConversationObserver] = field(default_factory=list)
    _inflight_id: MessageId | None = None

    def register_observer(self, observer: ConversationObserver) -> None:
        """Observers self-register in their own constructor (see
        SessionDisplay, SessionManager) — the composition root never wires
        them. The conversation only ever holds "things with these methods"; it
        never learns what any of them are."""
        self._observers.append(observer)

    def _snapshot(self) -> Conversation:
        """A cheap copy of the current state, for handing to observers as the
        BEFORE of a destructive change. Copies the id→message mapping only —
        the message objects themselves are shared, and `self` keeps its own
        identity (pydantic-ai relies on it; see `adopt`)."""
        return Conversation(usage=self.usage, _entries=dict(self._entries))

    @property
    def messages(self) -> tuple[ModelMessage, ...]:
        """Ordered, immutable view - safe to hand to pydantic-ai or iterate."""
        return tuple(self._entries.values())

    @property
    def ids(self) -> tuple[MessageId, ...]:
        return tuple(self._entries.keys())

    def get(self, message_id: MessageId) -> ModelMessage | None:
        return self._entries.get(message_id)

    async def append(self, message: ModelMessage) -> MessageId:
        message_id = str(uuid.uuid4())
        self._entries[message_id] = message
        for observer in self._observers:
            await observer.message_added(message_id)
        return message_id

    async def edit(self, message_id: MessageId, part_index: int, new_text: str) -> None:
        """Overwrite an editable text part's content in place, then notify.
        Caller (a UI) supplies the (message_id, part_index) it captured at
        render - both stable, since messages are id-keyed and parts are
        append-only within a message."""
        part = self._entries[message_id].parts[part_index]
        if not isinstance(part, _EDITABLE_PARTS):
            raise ValueError(f"{type(part).__name__} is not an editable part")
        part.content = new_text
        for observer in self._observers:
            await observer.message_edited(message_id)

    def _cut(self, message_id: MessageId) -> bool:
        """Drop `message_id` and every entry after it (by insertion order).
        False if the id isn't present (caller should not notify)."""
        if message_id not in self._entries:
            return False
        keys = list(self._entries.keys())
        for key in keys[keys.index(message_id) :]:
            del self._entries[key]
        return True

    async def truncate_from(self, message_id: MessageId) -> None:
        """Rewind in place, discarding `message_id` onward — Delete and Retry.
        What is dropped is gone; nothing is preserved. No-op + no notify if the
        id isn't present."""
        if not self._cut(message_id):
            return
        for observer in self._observers:
            await observer.truncated_from(message_id)

    async def branch_from(self, message_id: MessageId) -> None:
        """Rewind, but hand observers the conversation as it was — Branch.

        Identical to `truncate_from` except for the event, which is the whole
        point: persistence writes the pre-rewind state to a new file, and the
        caller doesn't have to know that files exist. The BEFORE has to be
        captured here because by the time anyone is notified the entries are
        gone."""
        if message_id not in self._entries:
            return
        previous = self._snapshot()
        self._cut(message_id)
        for observer in self._observers:
            await observer.branched_from(message_id, previous)

    def reidentify(self, message_id: MessageId, message: ModelMessage) -> None:
        """Silently swap the object stored under an existing id (no observer
        event). Used for optimistic echo: we mount the user's prompt instantly
        under `message_id`, then fold pydantic-ai's own equal-content request
        object into that same id so `adopt` sees it as already-present (no
        duplicate) and the mounted widget stays put."""
        if message_id in self._entries:
            self._entries[message_id] = message

    async def adopt(self, messages: Sequence[ModelMessage]) -> None:
        """Reconcile to pydantic-ai's authoritative message list. A message
        already held (by object identity) keeps its id; any genuinely-new
        message object is appended (new id + message_added). Nothing is
        removed. Idempotent - adopting the same list twice mounts nothing new.
        Identity, not index/content: pydantic-ai preserves the object identity
        of the history we pass into agent.iter(), so id() is the reliable key.
        NOTE: that identity preservation is a load-bearing pydantic-ai invariant
        (a version that deep-copied message_history would make this double-mount);
        it's pinned by test_pydantic_ai_preserves_message_history_object_identity."""
        held = {id(message) for message in self._entries.values()}
        for message in messages:
            if id(message) not in held:
                await self.append(message)

    async def load(self, messages: Sequence[ModelMessage], usage: RunUsage) -> None:
        """Replace the whole conversation (session resume / replay), reactively.

        ONE event, fired once the new history is fully in place: an observer
        reacting to it sees the finished conversation and walks it however it
        likes. A load deliberately does NOT replay itself as a burst of
        `message_added` — the arrival of a live message and the wholesale
        replacement of the history are different things, and an observer that
        needs to tell them apart (a display redrawing recorded tool calls) must
        not have to infer it from what happens to be queryable at the time.

        `previous` is the history being replaced, for symmetry with
        `branched_from` — the destructive events all hand over their BEFORE,
        since by the time anyone is notified the entries are gone.

        Fires `conversation_loaded`, NOT `truncated_from`: nothing is being
        discarded here, the history is being adopted from somewhere else.
        Persistence must not react to a load by writing back over the file it
        just read."""
        previous = self._snapshot()
        self._entries = {str(uuid.uuid4()): message for message in messages}
        self._inflight_id = None
        self.usage = usage
        for observer in self._observers:
            await observer.conversation_loaded(previous)

    async def begin_stream(self, response: ModelMessage) -> MessageId:
        """Start streaming a model response: hold the current snapshot as a
        live entry. Held by _inflight_id; each stream_updated swaps in a newer
        snapshot until finalize_stream installs the canonical object.

        Fires `stream_began`, NOT `message_added`: this entry is provisional
        and will be replaced. A display mounts it; persistence waits."""
        message_id = str(uuid.uuid4())
        self._entries[message_id] = response
        self._inflight_id = message_id
        for observer in self._observers:
            await observer.stream_began(message_id)
        return message_id

    async def stream_updated(self, response: ModelMessage) -> None:
        """A streamed token landed - install the latest snapshot and re-render.
        pydantic-ai's `stream.response` builds a fresh immutable ModelResponse
        per access (it never mutates in place), so the caller passes the current
        snapshot and we swap it under the in-flight id. No-op when not
        streaming."""
        if self._inflight_id is not None:
            self._entries[self._inflight_id] = response
            for observer in self._observers:
                await observer.stream_updated(self._inflight_id)

    async def finalize_stream(self, response: ModelMessage) -> None:
        """Replace the in-flight streamed object with pydantic-ai's canonical
        finalized response under the same id, so a later adopt() sees it as
        already present (no duplicate) and the entry's id stays stable. No-op
        when not streaming."""
        if self._inflight_id is None:
            return
        self._entries[self._inflight_id] = response
        for observer in self._observers:
            await observer.stream_completed(self._inflight_id)
        self._inflight_id = None
