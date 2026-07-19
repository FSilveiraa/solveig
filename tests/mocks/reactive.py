"""Headless ReactiveTranscript for tests - records materialization instead of
drawing, so the full Conversation -> observer -> materialize chain is assertable
without Textual."""

from __future__ import annotations

from pydantic_ai.messages import TextPart, ThinkingPart, UserPromptPart

from solveig.conversation import Conversation, MessageId
from solveig.interface.reactive import ReactiveTranscript


def _contents(message) -> list[str]:
    """The non-empty conversational text a message would render, in order."""
    out: list[str] = []
    for part in message.parts:
        if isinstance(part, UserPromptPart) and isinstance(part.content, str):
            text = part.content
        elif isinstance(part, (TextPart, ThinkingPart)):
            text = part.content
        else:
            continue
        if text.strip():
            out.append(text)
    return out


class RecordingTranscript(ReactiveTranscript):
    def __init__(self, conversation: Conversation) -> None:
        self.mounted: dict[MessageId, list[str]] = {}
        self.events: list[tuple] = []
        super().__init__(conversation)

    def _present(self, message_id: MessageId) -> list[str]:
        message = self.conversation.get(message_id)
        return _contents(message) if message is not None else []

    async def mount(self, message_id: MessageId) -> None:
        self.mounted[message_id] = self._present(message_id)
        self.events.append(("mount", message_id))

    async def rerender(self, message_id: MessageId) -> None:
        self.mounted[message_id] = self._present(message_id)
        self.events.append(("rerender", message_id))

    async def remove(self, message_ids: list[MessageId]) -> None:
        for mid in message_ids:
            self.mounted.pop(mid, None)
        self.events.append(("remove", tuple(message_ids)))
