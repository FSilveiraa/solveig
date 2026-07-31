"""Textual materialization of the reactive transcript (Surface-1).

Observes the Conversation and mounts CLOSED-content parts (user/assistant text,
reasoning) as widgets into the ConversationArea, keyed by message_id.

Tool call/return parts are deliberately NOT rendered here: a tool is not a
1:1-presentable concept (its display is a flow, not one widget), so
`_make_widget` returns None for it and the tool owns its own display via
execute()/replay(). Never teach this transcript about tools.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    UserPromptPart,
)
from textual.widget import Widget
from textual.widgets import Markdown as MarkdownWidget

from solveig.conversation import Conversation, MessageId
from solveig.interface.reactive import ReactiveTranscript
from solveig.sessions.replay import build_returns_map, replay_tool_call

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


class TextualTranscript(ReactiveTranscript):
    def __init__(
        self,
        conversation: Conversation,
        area: ConversationArea,
        interface: SolveigInterface,
    ) -> None:
        self._area = area
        self._interface = interface
        self._widgets: dict[MessageId, list[Widget]] = {}
        self._last_section_role: str | None = None
        super().__init__(conversation)

    async def mount(self, message_id: MessageId) -> None:
        message = self.conversation.get(message_id)
        if message is None:
            return
        role = _role_of(message)
        widgets: list[Widget] = []

        if role is not None and role != self._last_section_role:
            header = SectionHeader(role.capitalize())
            await self._mount_widget(header)
            widgets.append(header)
            self._last_section_role = role

        returns = None
        for part_index, part in enumerate(message.parts):
            widget = self._make_widget(part, message_id, part_index, role)
            if widget is not None:
                await self._mount_widget(widget)
                widgets.append(widget)
            elif isinstance(part, ToolCallPart):
                # A tool call renders itself (the tool's own replay: header +
                # result) only once its result is present - which it is on
                # replay (load populates the whole history first) but not on a
                # live run (execute() shows the tool live before the result
                # exists, so this is skipped and there's no double render).
                if returns is None:
                    returns = build_returns_map(self.conversation.messages)
                return_part = returns.get(part.tool_call_id)
                if return_part is not None:
                    await replay_tool_call(self._interface, part, return_part)

        self._widgets[message_id] = widgets

    async def rerender(self, message_id: MessageId) -> None:
        """Update this message's widgets in place (edit or streaming). Content
        widgets are updated where they already exist and appended for parts that
        appeared since (streaming only ever appends parts, and the streamed
        message is always the last one, so appending stays in order)."""
        message = self.conversation.get(message_id)
        if message is None:
            return
        role = _role_of(message)
        existing = self._widgets.get(message_id, [])
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
        self._widgets[message_id] = existing

    async def remove(self, message_ids: list[MessageId]) -> None:
        for message_id in message_ids:
            for widget in self._widgets.pop(message_id, []):
                await widget.remove()
        self._last_section_role = self._recompute_section_role()

    # -- helpers ------------------------------------------------------------

    async def _mount_widget(self, widget: Widget) -> None:
        await self._area._add_element(widget, self._area)

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
        """The role of the last still-mounted role-bearing message, so the next
        mount emits a section header only on a genuine role change."""
        for message_id in reversed(self.conversation.ids):
            role = _role_of(self.conversation.get(message_id))
            if role is not None:
                return role
        return None
