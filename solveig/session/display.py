"""SessionDisplay - the observer that puts a conversation on screen.

The peer of `SessionManager`: both watch the same Conversation, one to save it,
one to show it. Everything about "what should be visible right now" lives here,
so a frontend is left with a single job - materialize what it is told to.

Two kinds of part have to be interleaved and only this layer can do both:

- a conversational part (a prompt, the assistant's text, its reasoning) is one
  widget the frontend knows how to build, so it is handed straight over;
- a tool call is not a widget at all. Its live display is a FLOW that
  `run_tool_and_hooks` already drew while the tool ran; what survives in the
  history is a recorded call plus its result, which `replay_tool_call` can
  re-present. A frontend must never learn any of that.

Redrawing a recorded call happens ONLY on `conversation_loaded`, which is the
literal event for "this history came from somewhere else". Live calls were
drawn as they ran, so there is nothing to redraw and no double render - a fact
of which event fired, not a guess from whether a result happens to be present
yet.

Interface-agnostic: no Textual, no colour, no drawing. Textual materializes a
part into a widget; a web frontend would materialize it into DOM over the same
three protocol methods.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.messages import ToolCallPart, ToolReturnPart

from solveig.session.conversation import Conversation, ConversationObserver, MessageId
from solveig.tools.available import tool_classes
from solveig.tools.base import BaseTool
from solveig.tools.orchestration import build_returns_map, replay_tool_call

if TYPE_CHECKING:
    from solveig.interface.base import SolveigInterface


class SessionDisplay(ConversationObserver):
    """Absorbs the conversation's event set into the frontend's three display
    methods, so a frontend never sees the extra granularity: streaming,
    completion and edits are all just "redraw this one", and both kinds of
    rewind are just "drop these". Persistence needs the distinctions; a display
    does not.

    Keeps its own insertion-ordered projection of shown ids so a truncation can
    compute the tail to drop - by the time `truncated_from` fires, the
    conversation has already removed those entries, so the tail can only come
    from this projection.
    """

    def __init__(self, conversation: Conversation, interface: SolveigInterface) -> None:
        self.conversation = conversation
        self.interface = interface
        self._order: list[MessageId] = []
        conversation.register_observer(self)

    # -- conversation events --------------------------------------------------

    async def message_added(self, message_id: MessageId) -> None:
        await self._display_message(message_id)

    async def stream_began(self, message_id: MessageId) -> None:
        await self._display_message(message_id)

    async def stream_updated(self, message_id: MessageId) -> None:
        await self.interface.update_message(message_id)

    async def stream_completed(self, message_id: MessageId) -> None:
        await self.interface.update_message(message_id)

    async def message_edited(self, message_id: MessageId) -> None:
        await self.interface.update_message(message_id)

    async def truncated_from(self, message_id: MessageId) -> None:
        await self._drop_from(message_id)

    async def branched_from(
        self, message_id: MessageId, previous: Conversation
    ) -> None:
        # A branch looks identical on screen; `previous` is persistence's business.
        await self._drop_from(message_id)

    async def conversation_loaded(self, previous: Conversation) -> None:
        """A resume replaces the history wholesale: drop whatever is up, then
        walk the loaded history. This is the one path that redraws recorded
        tool calls - see the module docstring."""
        # NOTE: a load drops EVERY shown id, so the whole list goes over in a
        # single drop_messages and the frontend can unmount it in one batch.
        # It canNOT answer this by wiping its container: the surface holds
        # things the transcript never mounted (banner, system prompt, tool
        # groups), and on a resume the system prompt is displayed BEFORE the
        # load. Bulk removal is the frontend's business; a second "clear
        # everything" verb would only make every frontend write two drops.
        if self._order:
            dropped, self._order = self._order, []
            await self.interface.drop_messages(dropped)
        returns = build_returns_map(self.conversation.messages)
        # Both indexes are built once per load and threaded down, rather than
        # rebuilt per part.
        classes = tool_classes()
        for message_id in self.conversation.ids:
            await self._display_message(message_id, returns=returns, classes=classes)

    # -- helpers --------------------------------------------------------------

    async def _display_message(
        self,
        message_id: MessageId,
        returns: dict[str, ToolReturnPart] | None = None,
        classes: dict[str, type[BaseTool]] | None = None,
    ) -> None:
        """Walk a message's parts IN ORDER, sending each to whoever can draw it.

        Part-by-part rather than message-at-a-time because that is the only
        granularity at which a tool call can appear between two pieces of text
        and come out in the right place. `update_message`/`drop_messages` stay
        message-level: neither has anything to interleave.
        """
        message = self.conversation.get(message_id)
        if message is None:
            return
        if message_id not in self._order:
            self._order.append(message_id)
        for part_index, part in enumerate(message.parts):
            if returns is not None and isinstance(part, ToolCallPart):
                recorded = returns.get(part.tool_call_id)
                if recorded is not None:
                    # The class is resolved HERE, not inside replay_tool_call:
                    # name -> class means reading the tool registries, and
                    # `orchestration` has to stay importable by the very
                    # modules that declare them. This layer sits above tools,
                    # so it can look one up; that module cannot.
                    await replay_tool_call(
                        self.interface,
                        part,
                        recorded,
                        tool_cls=(classes or {}).get(part.tool_name),
                    )
                    continue
            await self.interface.show_message_part(message_id, part_index)

    async def _drop_from(self, message_id: MessageId) -> None:
        if message_id not in self._order:
            return
        cut = self._order.index(message_id)
        removed = self._order[cut:]
        self._order = self._order[:cut]
        await self.interface.drop_messages(removed)
