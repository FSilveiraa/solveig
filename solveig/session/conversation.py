"""Conversation - the reactive single source of truth for the message history.

One insertion-ordered `dict[MessageId, ModelMessage]` IS both the ordered list
(`.values()`, handed to pydantic-ai as message_history) and the id-index
(`d[id]`, O(1) lookup/edit/address). There is no separate list+map to keep in
sync, so drift and leaks are structurally impossible. Every mutation is an
async method that updates the dict and then awaits registered observers.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    TextPart,
    ThinkingPart,
    UserPromptPart,
)
from pydantic_ai.usage import RunUsage

MessageId = str

_EDITABLE_PARTS = (UserPromptPart, TextPart, ThinkingPart)


def parse_conversation_blob(text: str) -> dict:
    """Parse stored conversation data from raw text — two formats, one reader.

    **Legacy blob** (single JSON object, still used by story files):
        {"messages": [...], "total_tokens_sent": N, ...}

    **Log format** (one value per line, append-only session files):
        <ModelMessage>
        <ModelMessage>
        {"session_meta": true, "total_tokens_sent": N, ...}  ← optional, last one wins

    Detection: the first line's first char — legacy blobs start with '{' and
    contain a "messages" key; log lines start with '{' and contain either
    "kind" (a message) or "session_meta" (meta).  An empty file returns
    zero messages and zero totals.

    Stories are always legacy blobs; new session files use the log format.
    Old session files (written before the log-format cutover) keep loading.
    """
    text = text.strip()
    if not text:
        return {"messages": [], "total_tokens_sent": 0, "total_tokens_received": 0}

    # Legacy blob: single JSON object with a "messages" key.
    if text.startswith("{") and '"messages"' in text[:200]:
        blob = json.loads(text)
        return {
            "messages": ModelMessagesTypeAdapter.validate_python(blob["messages"]),
            "total_tokens_sent": blob.get("total_tokens_sent", 0),
            "total_tokens_received": blob.get("total_tokens_received", 0),
        }

    # Log format: one JSON value per line.
    messages: list[ModelMessage] = []
    total_sent = 0
    total_received = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("session_meta"):
            total_sent = obj.get("total_tokens_sent", 0)
            total_received = obj.get("total_tokens_received", 0)
        else:
            messages.extend(ModelMessagesTypeAdapter.validate_python([obj]))

    return {
        "messages": messages,
        "total_tokens_sent": total_sent,
        "total_tokens_received": total_received,
    }


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
    _assembly_id: MessageId | None = None

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

    async def reconcile(
        self,
        message_id: MessageId,
        canonical: ModelMessage,
        *,
        merge: Callable[[ModelMessage, ModelMessage], ModelMessage] | None = None,
        announce: bool = True,
    ) -> None:
        """The one reconciliation rule: a provisional entry we built IS the
        message pydantic-ai has now built for itself. Keep our id, end up
        holding THEIR object.

        Holding their object is the load-bearing half. `adopt` matches by object
        identity, so an entry left holding our copy makes their equal-content
        object look new and mounts a duplicate.

        `merge` covers the case where our copy knows something theirs does not
        (user comments interleaved between tool returns exist nowhere else), and
        must fold that into their object rather than replacing it.

        `announce=False` for a swap that changes nothing visible - the optimistic
        prompt echo, where both objects carry the same text and a re-render would
        be pure churn."""
        if message_id not in self._entries:
            return
        if merge is not None:
            canonical = merge(self._entries[message_id], canonical)
        self._entries[message_id] = canonical
        # Whichever provisional slot this entry occupied is now settled.
        if self._inflight_id == message_id:
            self._inflight_id = None
        if self._assembly_id == message_id:
            self._assembly_id = None
        if announce:
            for observer in self._observers:
                await observer.stream_completed(message_id)

    async def reidentify(self, message_id: MessageId, message: ModelMessage) -> None:
        """Optimistic echo: we mount the user's prompt instantly, then fold
        pydantic-ai's own equal-content request object into that same id."""
        await self.reconcile(message_id, message, announce=False)

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
        # Both provisional slots: a load replaces the history wholesale, so
        # anything half-built belonged to the conversation being discarded.
        self._inflight_id = None
        self._assembly_id = None
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
        """The streamed response is complete: swap in pydantic-ai's canonical
        object. No-op when not streaming."""
        if self._inflight_id is not None:
            await self.reconcile(self._inflight_id, response)

    # -- an entry assembled part-by-part --------------------------------------
    #
    # The mirror of the streaming trio above, for the other direction: a
    # ModelRequest that grows as tool returns land, rather than a ModelResponse
    # that grows as tokens land. Both are "a provisional entry that will be
    # replaced by pydantic-ai's canonical object", so they reuse the SAME
    # observer events - a display mounts and re-renders either one identically,
    # and persistence waits for either one the same way. Adding a parallel event
    # set would make every observer implement three methods to do what it
    # already does.
    #
    # A separate slot from `_inflight_id`, though: a cancelled response stream
    # can leave that one occupied, and the two must not clobber each other.

    @property
    def assembling(self) -> bool:
        """Whether an entry is mid-assembly and still awaiting the canonical
        object that will replace it."""
        return self._assembly_id is not None

    @property
    def assembly(self) -> ModelMessage | None:
        """The entry currently being assembled, so a caller reconciling it with
        a canonical object can see what it built."""
        if self._assembly_id is None:
            return None
        return self._entries[self._assembly_id]

    async def begin_assembly(self, message: ModelMessage) -> MessageId:
        """Start an entry that will grow. Returns its id; the caller passes each
        successive whole message to `assembly_updated`."""
        message_id = str(uuid.uuid4())
        self._entries[message_id] = message
        self._assembly_id = message_id
        for observer in self._observers:
            await observer.stream_began(message_id)
        return message_id

    async def assembly_updated(self, message: ModelMessage) -> None:
        """A part landed - install the grown message and re-render. Takes the
        whole message rather than the new part, so the entry is never a
        half-built object an observer could read mid-mutation. No-op when
        nothing is being assembled."""
        if self._assembly_id is not None:
            self._entries[self._assembly_id] = message
            for observer in self._observers:
                await observer.stream_updated(self._assembly_id)

    async def finalize_assembly(
        self,
        message: ModelMessage,
        *,
        merge: Callable[[ModelMessage, ModelMessage], ModelMessage] | None = None,
    ) -> None:
        """The assembled entry's canonical object has arrived. `merge` folds in
        whatever only our copy knew. No-op when nothing is being assembled."""
        if self._assembly_id is not None:
            await self.reconcile(self._assembly_id, message, merge=merge)
