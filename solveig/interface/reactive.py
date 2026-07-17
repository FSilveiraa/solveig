"""Reactive transcript: Surface-1 of the interface contract (spec §5).

A ReactiveTranscript subscribes to a Conversation and reflects its change
events onto a concrete surface. It fetches the changed message by id, runs it
through the Presenter, and delegates the materialized nodes to three abstract
hooks (mount / rerender / remove) a concrete interface implements. It keeps its
own insertion-ordered projection of mounted ids so a truncation can compute the
tail to drop - by the time truncated_from fires, core has already removed those
entries, so the tail can only come from the interface's own projection.

Interface-agnostic: no Textual, no color, no drawing here - only fetch-by-id,
present, and delegate. Textual materializes nodes into widgets; a web frontend
materializes the same nodes into DOM over the same three hooks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from solveig.conversation import Conversation, MessageId
from solveig.interface.presenter import present_message
from solveig.interface.render import RenderNode


class ReactiveTranscript(ABC):
    def __init__(self, conversation: Conversation) -> None:
        self.conversation = conversation
        self._order: list[MessageId] = []
        conversation.subscribe(self)

    def _present(self, message_id: MessageId) -> list[RenderNode]:
        message = self.conversation.get(message_id)
        return present_message(message) if message is not None else []

    async def message_added(self, message_id: MessageId) -> None:
        self._order.append(message_id)
        await self.mount(message_id, self._present(message_id))

    async def message_updated(self, message_id: MessageId) -> None:
        await self.rerender(message_id, self._present(message_id))

    async def truncated_from(self, message_id: MessageId) -> None:
        if message_id not in self._order:
            return
        cut = self._order.index(message_id)
        removed = self._order[cut:]
        self._order = self._order[:cut]
        await self.remove(removed)

    @abstractmethod
    async def mount(self, message_id: MessageId, nodes: list[RenderNode]) -> None: ...

    @abstractmethod
    async def rerender(
        self, message_id: MessageId, nodes: list[RenderNode]
    ) -> None: ...

    @abstractmethod
    async def remove(self, message_ids: list[MessageId]) -> None: ...
