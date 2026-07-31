"""Reactive transcript: Surface-1 of the interface contract (spec §5).

A ReactiveTranscript subscribes to a Conversation and reflects its change
events onto a concrete surface via three abstract hooks (mount / rerender /
remove) a concrete interface implements. It keeps its own insertion-ordered
projection of mounted ids so a truncation can compute the tail to drop - by the
time truncated_from fires, core has already removed those entries, so the tail
can only come from the interface's own projection.

Interface-agnostic: no Textual, no color, no drawing here. Textual materializes
messages into widgets; a web frontend would materialize them into DOM over the
same three hooks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from solveig.conversation import Conversation, MessageId


class ReactiveTranscript(ABC):
    """Absorbs the conversation's event set into three render hooks, so a
    frontend never sees the extra granularity: streaming, completion and edits
    are all just "redraw this one", and both kinds of rewind are just "drop
    these". Persistence needs the distinctions; a display does not."""

    def __init__(self, conversation: Conversation) -> None:
        self.conversation = conversation
        self._order: list[MessageId] = []
        conversation.register_observer(self)

    async def message_added(self, message_id: MessageId) -> None:
        self._order.append(message_id)
        await self.mount(message_id)

    async def stream_began(self, message_id: MessageId) -> None:
        self._order.append(message_id)
        await self.mount(message_id)

    async def stream_updated(self, message_id: MessageId) -> None:
        await self.rerender(message_id)

    async def stream_completed(self, message_id: MessageId) -> None:
        await self.rerender(message_id)

    async def message_edited(self, message_id: MessageId) -> None:
        await self.rerender(message_id)

    async def truncated_from(self, message_id: MessageId) -> None:
        await self._drop_from(message_id)

    async def branched_from(
        self, message_id: MessageId, previous: Conversation
    ) -> None:
        # A branch looks identical on screen; `previous` is persistence's business.
        await self._drop_from(message_id)

    async def conversation_loaded(self) -> None:
        """A resume replaces the history wholesale: clear, then the load's
        message_added events mount the new entries."""
        if self._order:
            dropped, self._order = self._order, []
            await self.remove(dropped)

    async def _drop_from(self, message_id: MessageId) -> None:
        if message_id not in self._order:
            return
        cut = self._order.index(message_id)
        removed = self._order[cut:]
        self._order = self._order[:cut]
        await self.remove(removed)

    @abstractmethod
    async def mount(self, message_id: MessageId) -> None: ...

    @abstractmethod
    async def rerender(self, message_id: MessageId) -> None: ...

    @abstractmethod
    async def remove(self, message_ids: list[MessageId]) -> None: ...
