"""Textual materialization of conversation messages.

Turns a message part into a widget in the ConversationArea, keyed by message_id,
and keeps the bookkeeping that needs (which widgets belong to which message, and
which role each was drawn as).

This is NOT an observer. `SessionDisplay` watches the conversation and calls
`TerminalInterface`'s three transcript verbs, which delegate here - so nothing
in this file knows what a tool is, what a session is, or when a message arrived
versus when it was loaded from disk. It knows how to draw a piece of text.

A part it has no rendering for (a tool call or return) yields no widget and is
skipped: a tool is not a 1:1-presentable concept - its display is a flow, not
one widget - so the tool owns its own display via execute()/replay(). Never
teach this file about tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    UserPromptPart,
)
from textual.widget import Widget
from textual.widgets import Markdown as MarkdownWidget

from solveig.session.conversation import Conversation, MessageId

from .collapsible_widgets import TextBoxWidget
from .widgets import EditableComment

if TYPE_CHECKING:
    from pydantic_ai.messages import (
        ModelMessage,
        ModelRequestPart,
        ModelResponsePart,
    )

    from solveig.interface.base import SolveigInterface

    from .conversation_area import ConversationArea


def _role_of(message: ModelMessage | None) -> str | None:
    """user / assistant for closed conversational turns; None for a message
    that carries no closed content of its own (e.g. a tool-return request), or
    for a missing message."""
    if isinstance(message, ModelResponse):
        return "assistant"
    if isinstance(message, ModelRequest) and any(
        isinstance(part, UserPromptPart) for part in message.parts
    ):
        return "user"
    return None


def _renderable_content(part: ModelRequestPart | ModelResponsePart) -> str | None:
    """The non-empty text a conversational part should show, or None if it
    carries nothing to render (empty, or not a conversational part - e.g. a
    tool call/return)."""
    if isinstance(part, UserPromptPart) and isinstance(part.content, str):
        return part.content if part.content.strip() else None
    if isinstance(part, (TextPart, ThinkingPart)):
        return part.content if part.content.strip() else None
    return None


@dataclass
class _Mounted:
    """What this frontend knows about one message it drew: the widgets it put on
    screen and the role it drew them as. ONE record, so a drop forgets both at
    once - two dicts keyed by message id would be two things to keep in step."""

    role: str | None
    widgets: list[Widget] = field(default_factory=list)


class MessageDisplay:
    def __init__(
        self,
        conversation: Conversation,
        area: ConversationArea,
        interface: SolveigInterface,
    ) -> None:
        self.conversation = conversation
        self._area = area
        self._interface = interface
        # Insertion-ordered, so iteration order IS mount order. This is the only
        # honest description of what is on screen: by the time `drop` runs the
        # conversation already describes the state AFTER the change, which for a
        # load is a history that has not been drawn yet.
        self._mounted: dict[MessageId, _Mounted] = {}

    async def display(self, message_id: MessageId, *part_indexes: int) -> None:
        """Mount one part's widget. Called once per part, in order."""
        message = self.conversation.get(message_id)
        if message is None or any(
            index >= len(message.parts) for index in part_indexes
        ):
            return
        role = _role_of(message)
        mounted = self._mounted.setdefault(message_id, _Mounted(role=role))

        widgets = [
            widget
            for widget in [
                self._make_widget(message.parts[index], message_id, index, role)
                for index in part_indexes
            ]
            if widget
        ]
        if widgets:
            await self._mount_widget(*widgets)
            mounted.widgets.extend(widgets)

    async def update(self, message_id: MessageId) -> None:
        """Update this message's widgets in place (edit or streaming). Content
        widgets are updated where they already exist and appended for parts that
        appeared since (streaming only ever appends parts, and the streamed
        message is always the last one, so appending stays in order)."""
        message = self.conversation.get(message_id)
        if message is None:
            return
        role = _role_of(message)
        mounted = self._mounted.setdefault(message_id, _Mounted(role=role))
        existing = mounted.widgets

        rendered = 0
        for part_index, part in enumerate(message.parts):
            content = _renderable_content(part)
            if content is None:
                continue
            if rendered < len(existing):
                await self._update_widget(existing[rendered], content)
            else:
                widget = self._make_widget(part, message_id, part_index, role)
                if widget is not None:
                    await self._mount_widget(widget)
                    existing.append(widget)
            rendered += 1

    async def drop(self, message_ids: list[MessageId]) -> None:
        """Unmount every widget belonging to these messages in ONE structural
        change and ONE layout pass.

        `batch()` takes the widget lock and suppresses intermediate refreshes;
        `remove_children` prunes the whole set at once. Deliberately serialized
        - Textual's own bulk API acquires that lock, and racing DOM mutations
        (e.g. gathering N `widget.remove()` calls) would parallelize nothing:
        these are tree edits, not I/O.

        PRECONDITION: every widget handed over is an IMMEDIATE child of the
        conversation area. `remove_children` does not verify it - given an
        iterable it prunes with `parent=self` and trusts the caller. True here
        because `_mount_widget` mounts into the area itself; a widget mounted
        somewhere nested (a tool's group, which this class does not own) must
        never end up in a record.
        """
        doomed = [
            widget
            for message_id in message_ids
            for widget in self._forget(message_id).widgets
        ]
        if doomed:
            async with self._area.batch():
                await self._area.remove_children(doomed)

    def _forget(self, message_id: MessageId) -> _Mounted:
        """Drop this message's record and hand it back - one pop, so the
        widgets and the role it was drawn as can never fall out of step."""
        return self._mounted.pop(message_id, _Mounted(role=None))

    # -- helpers ------------------------------------------------------------

    async def _mount_widget(self, *widgets: Widget) -> None:
        await self._area.add_element(self._area, *widgets)

    def _make_widget(
        self,
        part: ModelRequestPart | ModelResponsePart,
        message_id: MessageId,
        part_index: int,
        role: str | None,
    ) -> Widget | None:
        """The one widget a conversational part becomes, or None if it carries
        no closed content to show (empty, or a tool call/return - a tool owns
        its own display). Reasoning -> collapsed box; user/assistant text ->
        editable comment."""
        content = _renderable_content(part)
        if content is None:
            return None
        if isinstance(part, ThinkingPart):
            # The widget, not a `TextBox` handle: this is the frontend mounting
            # into its own transcript, not a value crossing the protocol.
            return TextBoxWidget(
                content, title="Reasoning", italic=True, collapsed=True
            )
        return EditableComment(
            content,
            conversation=self.conversation,
            interface=self._interface,
            message_id=message_id,
            part_index=part_index,
            role="user" if role == "user" else "assistant",
        )

    async def _update_widget(self, widget: Widget, content: str) -> None:
        if isinstance(widget, EditableComment):
            widget.comment = content
            for markdown in widget.query(MarkdownWidget):
                await markdown.update(f"🗩 ⠀{content}")
                break
        elif isinstance(widget, TextBoxWidget):
            widget.update_content(content)
