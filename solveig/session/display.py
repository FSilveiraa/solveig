"""SessionDisplay - the observer that puts a conversation on screen.

The peer of `SessionManager`: both watch the same Conversation, one to save it,
one to show it. Everything about "what should be visible right now" lives here,
so a frontend is left with a single job - materialize what it is told to.

This is also where a model message stops being one. A part is decoded to the
text it should show (`_renderable_text`), a message to who it is from
(`_role_of`), and the buttons a message may offer to closures that already know
which message they act on. What crosses into a frontend is text, a role and a
set of actions - never a `ModelMessage`, never a `MessageId`. Two frontends had
each hand-rolled that decoding before this moved; a third would have been a
third copy with nothing making them agree.

Two kinds of part have to be interleaved and only this layer can do both:

- a conversational part (a prompt, the assistant's text, its reasoning) is one
  message the frontend knows how to draw, so its text is handed straight over;
- a tool call is not one drawable thing at all. Its live display is a FLOW that
  `run_tool_and_hooks` already drew while the tool ran; what survives in the
  history is a recorded call plus its result, which `replay_tool_call` can
  re-present. A frontend must never learn any of that.

Redrawing a recorded call happens ONLY on `conversation_loaded`, which is the
literal event for "this history came from somewhere else". Live calls were
drawn as they ran, so there is nothing to redraw and no double render - a fact
of which event fired, not a guess from whether a result happens to be present
yet.

Interface-agnostic: no Textual, no colour, no drawing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from solveig.interface.base import MessageActions, MessageBox, Role
from solveig.session.conversation import Conversation, ConversationObserver, MessageId
from solveig.tools.available import tool_classes
from solveig.tools.base import BaseTool
from solveig.tools.orchestration import build_returns_map, replay_tool_call

if TYPE_CHECKING:
    from pydantic_ai.messages import (
        ModelMessage,
        ModelRequestPart,
        ModelResponsePart,
    )

    from solveig.interface.base import SolveigInterface
    from solveig.user_message_queue import UserMessageQueue


def _role_of(message: ModelMessage | None) -> Role | None:
    """Who a closed conversational turn is from; None for a message that
    carries no closed content of its own (e.g. a tool-return request), or for a
    missing message."""
    if isinstance(message, ModelResponse):
        return Role.ASSISTANT
    if isinstance(message, ModelRequest) and any(
        isinstance(part, UserPromptPart) for part in message.parts
    ):
        return Role.USER
    return None


def _renderable_text(part: ModelRequestPart | ModelResponsePart) -> str | None:
    """The non-empty text a conversational part should show, or None if it
    carries nothing to render (empty, or not a conversational part - e.g. a
    tool call/return)."""
    if isinstance(part, UserPromptPart) and isinstance(part.content, str):
        return part.content if part.content.strip() else None
    if isinstance(part, TextPart | ThinkingPart):
        return part.content if part.content.strip() else None
    return None


class SessionDisplay(ConversationObserver):
    """Absorbs the conversation's event set into two display verbs, so a
    frontend never sees the extra granularity: streaming, completion and edits
    are all just "restate this one", and both kinds of rewind are just "take
    these back". Persistence needs the distinctions; a display does not.

    Keeps the handles it was given back, insertion-ordered by message id. That
    ONE structure answers everything the display side needs: which messages are
    up (so a truncation can compute the tail - by the time `truncated_from`
    fires the conversation has already dropped them), which handle to restate
    when a part changes, and what to remove. It replaces both the id list this
    class used to keep and the mounted-widget map the frontend used to keep.
    """

    def __init__(
        self,
        conversation: Conversation,
        interface: SolveigInterface,
        user_message_queue: UserMessageQueue | None = None,
    ) -> None:
        self.conversation = conversation
        self.interface = interface
        # NOTE: taken by constructor injection rather than read off the
        # interface. The queue is the session's, not the frontend's - reaching
        # through `interface.user_message_queue` for it would make the frontend
        # the way app objects are found, which is the coupling this class
        # exists to avoid.
        self.user_message_queue = user_message_queue
        self._boxes: dict[MessageId, list[MessageBox]] = {}
        conversation.register_observer(self)

    # -- conversation events --------------------------------------------------

    async def message_added(self, message_id: MessageId) -> None:
        await self._display_message(message_id)

    async def stream_began(self, message_id: MessageId) -> None:
        await self._display_message(message_id)

    async def stream_updated(self, message_id: MessageId) -> None:
        await self._restate(message_id)

    async def stream_completed(self, message_id: MessageId) -> None:
        await self._restate(message_id)

    async def message_edited(self, message_id: MessageId) -> None:
        await self._restate(message_id)

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
        # NOTE: it canNOT be answered by wiping the frontend's container: the
        # surface holds things the transcript never mounted (banner, system
        # prompt, tool groups), and on a resume the system prompt is displayed
        # BEFORE the load. Only the handles we are holding may be removed.
        for message_id in list(self._boxes):
            await self._forget(message_id)
        returns = build_returns_map(self.conversation.messages)
        # Both indexes are built once per load and threaded down, rather than
        # rebuilt per part.
        classes = tool_classes()
        for message_id in self.conversation.ids:
            await self._display_message(message_id, returns=returns, classes=classes)

    # -- drawing --------------------------------------------------------------

    async def _display_message(
        self,
        message_id: MessageId,
        returns: dict[str, ToolReturnPart] | None = None,
        classes: dict[str, type[BaseTool]] | None = None,
    ) -> None:
        """Walk a message's parts IN ORDER, sending each to whoever can draw it.

        Part-by-part rather than message-at-a-time because that is the only
        granularity at which a tool call can appear between two pieces of text
        and come out in the right place.
        """
        message = self.conversation.get(message_id)
        if message is None:
            return
        # Recorded even when it draws nothing: an id that is up but empty still
        # has to be in the order, or a rewind to it would find no cut point.
        boxes = self._boxes.setdefault(message_id, [])
        role = _role_of(message)
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
            box = await self._draw(part, message_id, part_index, role)
            if box is not None:
                boxes.append(box)

    async def _restate(self, message_id: MessageId) -> None:
        """Bring an already-drawn message up to date - a streamed token landed,
        a stream finished, or the user edited it.

        Handles are aligned with RENDERABLE parts, not with part indexes: a
        message may carry parts that draw nothing (a tool call), so the nth
        handle is the nth thing that drew. A part that appeared since (streaming
        only ever appends, and to the last message) is drawn and appended.
        """
        message = self.conversation.get(message_id)
        if message is None:
            return
        boxes = self._boxes.setdefault(message_id, [])
        role = _role_of(message)
        drawn = 0
        for part_index, part in enumerate(message.parts):
            text = _renderable_text(part)
            if text is None:
                continue
            if drawn < len(boxes):
                await boxes[drawn].replace(text)
            else:
                box = await self._draw(part, message_id, part_index, role)
                if box is not None:
                    boxes.append(box)
            drawn += 1

    async def _draw(
        self,
        part: ModelRequestPart | ModelResponsePart,
        message_id: MessageId,
        part_index: int,
        role: Role | None,
    ) -> MessageBox | None:
        """The one box a conversational part becomes, or None if it carries
        nothing to show (empty, or a tool call/return - a tool owns its own
        display)."""
        text = _renderable_text(part)
        if text is None:
            return None
        if isinstance(part, ThinkingPart):
            return await self.interface.add_reasoning(text)
        return await self.interface.add_message(
            text,
            role or Role.ASSISTANT,
            self._actions_for(message_id, part_index, role),
        )

    # -- rewinding ------------------------------------------------------------

    async def _drop_from(self, message_id: MessageId) -> None:
        if message_id not in self._boxes:
            return
        ids = list(self._boxes)
        for doomed in ids[ids.index(message_id) :]:
            await self._forget(doomed)

    async def _forget(self, message_id: MessageId) -> None:
        """Take a message off the display and stop holding its handles - one
        pop, so what is on screen and what we think is on screen cannot drift."""
        for box in self._boxes.pop(message_id, []):
            await box.remove()

    # -- actions --------------------------------------------------------------

    def _actions_for(
        self, message_id: MessageId, part_index: int, role: Role | None
    ) -> MessageActions:
        """What may be done to this message, as closures over the id we already
        have here. A frontend gets capability, not identity.

        Retry is offered for user turns ONLY: regenerating an assistant response
        means editing and re-sending the user message before it. That rule lives
        here because it is a rule about the conversation, not about drawing.
        """
        return MessageActions(
            edit=lambda text: self._edit(message_id, part_index, text),
            retry=(lambda: self._retry(message_id)) if role is Role.USER else None,
            delete=lambda: self._delete(message_id),
            branch=lambda: self._branch(message_id),
        )

    async def _busy(self) -> bool:
        """Whether a mutation must be refused right now, having said so.

        A history mutation mid-run is reconciled away when `adopt()` re-syncs
        the conversation at run end, and a mid-run retry would be drained into
        the running turn as an interjection instead of starting fresh. The
        refusal is app policy, so it is decided here - a frontend that had to
        ask "is a run in flight" would be one more thing every frontend has to
        get right.
        """
        if not self.interface.get_active_tasks():
            return False
        await self.interface.set_status(
            "Finish or cancel the current run first", duration=3
        )
        return True

    async def _edit(self, message_id: MessageId, part_index: int, text: str) -> None:
        if await self._busy():
            return
        await self.conversation.edit(message_id, part_index, text)

    async def _retry(self, message_id: MessageId) -> None:
        if await self._busy():
            return
        # Read at CALL time, not captured when the message was drawn: an
        # edit-then-retry has to resubmit the edited text, and the edit went
        # into the conversation, not into whatever the button is holding.
        message = self.conversation.get(message_id)
        text = next(
            (
                _renderable_text(part)
                for part in (message.parts if message else [])
                if _renderable_text(part) is not None
            ),
            None,
        )
        await self.conversation.truncate_from(message_id)
        if text is not None and self.user_message_queue is not None:
            # check_subcommand=False: this text was already vetted when the user
            # first sent it. Re-gating would let a trigger the registry gained
            # since (a plugin reload, an MCP connect) swallow a stored prompt as
            # a command, and the message would simply vanish.
            await self.user_message_queue.put(text, check_subcommand=False)

    async def _delete(self, message_id: MessageId) -> None:
        if await self._busy():
            return
        await self.conversation.truncate_from(message_id)

    async def _branch(self, message_id: MessageId) -> None:
        if await self._busy():
            return
        # `branch_from` rather than `truncate_from`: same rewind, different
        # event, so persistence can preserve what's being dropped.
        await self.conversation.branch_from(message_id)
