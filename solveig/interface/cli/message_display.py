"""Textual materialization of conversation messages.

Turns a message part into a widget in the ConversationArea, keyed by message_id,
and keeps the bookkeeping that needs (which widgets belong to which message, and
which role the last section header announced).

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

from .collapsible_widgets import CollapsibleTextBox
from .widgets import EditableComment, SectionHeader

if TYPE_CHECKING:
    from pydantic_ai.messages import (
        ModelMessage,
        ModelRequestPart,
        ModelResponsePart,
    )

    from solveig.interface.base import SolveigInterface

    from .conversation import ConversationArea


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
    screen and the role it announced. ONE record, so a drop forgets both at once
    - two dicts keyed by message id would be two things to keep in step."""

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
        self._last_section_role: str | None = None

    async def display(self, message_id: MessageId, *part_indexes: int) -> None:
        # async def display(self, message_id: MessageId, part_index: int | None = None) -> None:
        """Mount one part's widget, emitting a section header first if this
        message opens a new role. Called once per part, in order, so the header
        check has to be idempotent - it is, since it only fires on a genuine
        role change."""
        message = self.conversation.get(message_id)
        if message is None or any(
            index >= len(message.parts) for index in part_indexes
        ):
            return
        role = _role_of(message)
        mounted = self._mounted.setdefault(message_id, _Mounted(role=role))

        if role is not None and role != self._last_section_role:
            header = SectionHeader(role.capitalize())
            await self._mount_widget(header)
            mounted.widgets.append(header)
            self._last_section_role = role

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
            mounted.widgets.append(*widgets)

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
        content_widgets = [w for w in existing if not isinstance(w, SectionHeader)]

        rendered = 0
        for part_index, part in enumerate(message.parts):
            content = _renderable_content(part)
            if content is None:
                continue
            if rendered < len(content_widgets):
                await self._update_widget(content_widgets[rendered], content)
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
        self._last_section_role = self._recompute_section_role()

    def _forget(self, message_id: MessageId) -> _Mounted:
        """Drop this message's record and hand it back - one pop, so the
        widgets and the role it announced can never fall out of step."""
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
            return CollapsibleTextBox(
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
        elif isinstance(widget, CollapsibleTextBox):
            widget.clear()
            widget.append(content)

    def _recompute_section_role(self) -> str | None:
        """The role of the last still-MOUNTED role-bearing message, so the next
        part shown emits a section header only on a genuine role change. Read
        from this object's own records, never from the conversation: after a
        load the conversation holds messages nothing has drawn yet, and
        trusting it there swallows the opening section header."""
        for mounted in reversed(self._mounted.values()):
            if mounted.role is not None:
                return mounted.role
        return None
