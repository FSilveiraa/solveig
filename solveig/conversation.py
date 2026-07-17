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
    however it likes (a UI schedules a throttled redraw)."""

    async def message_added(self, message_id: MessageId) -> None: ...
    async def message_updated(self, message_id: MessageId) -> None: ...
    async def truncated_from(self, message_id: MessageId) -> None: ...


@dataclass
class Conversation:
    usage: RunUsage = field(default_factory=RunUsage)
    _entries: dict[MessageId, ModelMessage] = field(default_factory=dict)
    _observers: list[ConversationObserver] = field(default_factory=list)
    _inflight_id: MessageId | None = None

    def subscribe(self, observer: ConversationObserver) -> None:
        self._observers.append(observer)

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
            await observer.message_updated(message_id)

    async def truncate_from(self, message_id: MessageId) -> None:
        """Drop `message_id` and every entry after it (by insertion order).
        No-op + no notify if the id isn't present."""
        if message_id not in self._entries:
            return
        keys = list(self._entries.keys())
        cut = keys.index(message_id)
        for key in keys[cut:]:
            del self._entries[key]
        for observer in self._observers:
            await observer.truncated_from(message_id)

    async def adopt(self, messages: Sequence[ModelMessage]) -> None:
        """Reconcile to pydantic-ai's authoritative message list. A message
        already held (by object identity) keeps its id; any genuinely-new
        message object is appended (new id + message_added). Nothing is
        removed. Idempotent - adopting the same list twice mounts nothing new.
        Identity, not index/content: pydantic-ai preserves the object identity
        of the history we pass into agent.iter(), so id() is the reliable key."""
        held = {id(message) for message in self._entries.values()}
        for message in messages:
            if id(message) not in held:
                await self.append(message)

    async def load(self, messages: Sequence[ModelMessage], usage: RunUsage) -> None:
        """Replace the whole conversation (session resume / replay). Drops any
        current entries (notifying), then appends each message so every one
        fires message_added - replay is just append-all, the same reactive
        path as a live turn."""
        if self._entries:
            await self.truncate_from(next(iter(self._entries)))
        self.usage = usage
        for message in messages:
            await self.append(message)

    async def begin_stream(self, response: ModelMessage) -> MessageId:
        """Start streaming a model response: append it as a live entry whose
        content the provider mutates in place as tokens arrive. Held by
        _inflight_id until finalize_stream swaps in the canonical object."""
        message_id = await self.append(response)
        self._inflight_id = message_id
        return message_id

    async def stream_updated(self) -> None:
        """A streamed token landed (the in-flight response mutated in place) -
        re-render it. No-op when not streaming."""
        if self._inflight_id is not None:
            for observer in self._observers:
                await observer.message_updated(self._inflight_id)

    async def finalize_stream(self, response: ModelMessage) -> None:
        """Replace the in-flight streamed object with pydantic-ai's canonical
        finalized response under the same id, so a later adopt() sees it as
        already present (no duplicate) and the entry's id stays stable. No-op
        when not streaming."""
        if self._inflight_id is None:
            return
        self._entries[self._inflight_id] = response
        for observer in self._observers:
            await observer.message_updated(self._inflight_id)
        self._inflight_id = None
