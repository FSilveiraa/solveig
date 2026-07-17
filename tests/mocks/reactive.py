"""Headless ReactiveTranscript for tests - records materialization instead of
drawing, so the full Conversation -> observer -> Presenter -> materialize chain
is assertable without Textual."""

from __future__ import annotations

from solveig.conversation import Conversation, MessageId
from solveig.interface.reactive import ReactiveTranscript
from solveig.interface.render import RenderNode


class RecordingTranscript(ReactiveTranscript):
    def __init__(self, conversation: Conversation) -> None:
        self.mounted: dict[MessageId, list[RenderNode]] = {}
        self.events: list[tuple] = []
        super().__init__(conversation)

    async def mount(self, message_id: MessageId) -> None:
        self.mounted[message_id] = self.present(message_id)
        self.events.append(("mount", message_id))

    async def rerender(self, message_id: MessageId) -> None:
        self.mounted[message_id] = self.present(message_id)
        self.events.append(("rerender", message_id))

    async def remove(self, message_ids: list[MessageId]) -> None:
        for mid in message_ids:
            self.mounted.pop(mid, None)
        self.events.append(("remove", tuple(message_ids)))
