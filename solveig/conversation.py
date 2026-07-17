"""Conversation - the reactive single source of truth for the message history.

One insertion-ordered `dict[MessageId, ModelMessage]` IS both the ordered list
(`.values()`, handed to pydantic-ai as message_history) and the id-index
(`d[id]`, O(1) lookup/edit/address). There is no separate list+map to keep in
sync, so drift and leaks are structurally impossible. Every mutation is an
async method that updates the dict and then awaits registered observers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol

from pydantic_ai.messages import ModelMessage
from pydantic_ai.usage import RunUsage

MessageId = str


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
