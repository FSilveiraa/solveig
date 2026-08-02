"""Headless conversation observer for tests.

The frontend counterpart of `MockInterface`: where that records what was
*displayed*, this records what the reactive layer decided to display. It
absorbs `Conversation`'s full event set into three display verbs —
`mount` / `rerender` / `remove` — the same reduction `SessionDisplay` performs
for a real frontend, so a test asserts on the reactive outcome without a
Textual app or a widget tree.

Why a mock rather than reusing `SessionDisplay`: that renders through a
`SolveigInterface` and resolves tool classes per load, dragging the whole
display stack into a test whose subject is `Conversation`'s event contract.

The three verbs are public and async ON PURPOSE — a test that needs to observe
*while* a stream is in flight subclasses one of them and calls `super()`
(`test_rerenders_show_growing_partial_content` does exactly this). Private
helpers would make that impossible.

Two projections, deliberately both kept:

- `mounted` — insertion-ordered {id: [rendered text, …]}, the live view.
  Compare its keys to `conversation.ids` to assert nothing was mounted twice or
  left behind; compare its values to assert what a frontend would be showing.
- `events` — the ordered log of (verb, id). Needed because `mounted` cannot
  show a rerender at all, and a test that cares about streaming (did a partial
  land before the cancel?) can only see it here.
"""

from __future__ import annotations

from pydantic_ai.messages import ModelMessage, TextPart, ThinkingPart, UserPromptPart

from solveig.session.conversation import (
    Conversation,
    ConversationObserver,
    MessageId,
)

# The parts that carry displayable text. Same set `Conversation` treats as
# editable — if a user can retype it, a frontend is showing it as text.
_TEXT_PARTS = (UserPromptPart, TextPart, ThinkingPart)


def _rendered(message: ModelMessage | None) -> list[str]:
    if message is None:
        return []
    return [
        part.content
        for part in message.parts
        if isinstance(part, _TEXT_PARTS) and isinstance(part.content, str)
    ]


class RecordingTranscript(ConversationObserver):
    """Self-registers on construction, mirroring how real observers wire
    themselves up (`SessionDisplay.__init__`) — a test constructs one and the
    conversation starts reporting to it."""

    def __init__(self, conversation: Conversation) -> None:
        self.conversation = conversation
        self.mounted: dict[MessageId, list[str]] = {}
        self.events: list[tuple[str, MessageId]] = []
        conversation.register_observer(self)

    # -- the three verbs ------------------------------------------------------

    async def mount(self, message_id: MessageId) -> None:
        self.mounted[message_id] = _rendered(self.conversation.get(message_id))
        self.events.append(("mount", message_id))

    async def rerender(self, message_id: MessageId) -> None:
        # Re-read rather than keep what mount() captured: streaming swaps a
        # NEWER snapshot object in under the same id (stream.response builds a
        # fresh ModelResponse per access and never mutates in place), so a
        # cached value would leave `mounted` frozen at empty while every event
        # still looked correct.
        self.mounted[message_id] = _rendered(self.conversation.get(message_id))
        self.events.append(("rerender", message_id))

    async def remove(self, message_ids: tuple[MessageId, ...]) -> None:
        """Batched on purpose - a truncation drops a whole tail and a load drops
        everything, and a real frontend unmounts that in one pass
        (`SolveigInterface.drop_messages`). One event per id would let a test
        pass against a frontend that thrashed the widget tree."""
        for message_id in message_ids:
            self.mounted.pop(message_id, None)
        self.events.append(("remove", message_ids))

    async def _remove_from(self, message_id: MessageId) -> None:
        # By the time a truncation fires, the entries are already gone from the
        # conversation, so the tail can only come from our own projection —
        # the same constraint `SessionDisplay` documents.
        ids = list(self.mounted)
        if message_id not in ids:
            return
        await self.remove(tuple(ids[ids.index(message_id) :]))

    # -- conversation events --------------------------------------------------

    async def message_added(self, message_id: MessageId) -> None:
        await self.mount(message_id)

    async def stream_began(self, message_id: MessageId) -> None:
        await self.mount(message_id)

    async def stream_updated(self, message_id: MessageId) -> None:
        await self.rerender(message_id)

    async def stream_completed(self, message_id: MessageId) -> None:
        await self.rerender(message_id)

    async def message_edited(self, message_id: MessageId) -> None:
        await self.rerender(message_id)

    async def truncated_from(self, message_id: MessageId) -> None:
        await self._remove_from(message_id)

    async def branched_from(
        self, message_id: MessageId, previous: Conversation
    ) -> None:
        # A branch looks identical on screen; `previous` is persistence's business.
        await self._remove_from(message_id)

    async def conversation_loaded(self, previous: Conversation) -> None:
        if self.mounted:
            await self.remove(tuple(self.mounted))
        for message_id in self.conversation.ids:
            await self.mount(message_id)
