"""Basic UI widgets for the Textual CLI interface."""

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from rich.syntax import Syntax
from textual.containers import ScrollableContainer
from textual.events import Click
from textual.widget import Widget
from textual.widgets import Markdown, Static

from solveig.exceptions import UserCancel
from solveig.interface.base import EditableMessage
from solveig.interface.themes import Palette
from solveig.utils.misc import copy_to_clipboard

from .buttons import BranchButton, DeleteButton, EditButton, RetryButton

if TYPE_CHECKING:
    from solveig.conversation import Conversation
    from solveig.interface.base import SolveigInterface
    from solveig.sessions.manager import SessionManager


class Comment(Static):
    def __init__(self, comment: str):
        super().__init__()
        self.comment = comment
        self.add_class("text_comment")

    def compose(self):
        yield Markdown(f"🗩 ⠀{self.comment}")
        yield CopyButton(self.comment)

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        return f"""
        .text_comment {{
            margin: 0 0 1 0;
        }}

        Markdown {{
            color: {theme.text};
            padding: 0;
        }}

        MarkdownBlock:last-of-type {{
            margin-bottom: 0;
        }}
        """


class EditableComment(Comment, EditableMessage):
    """A Comment tied to a specific `conversation.messages[msg_index].parts[part_index]`,
    with Edit/Retry/Delete/Branch action buttons. Retry only makes sense for
    user turns - regenerating an assistant response is Edit+Retry on the
    preceding user message instead."""

    def __init__(
        self,
        comment: str,
        *,
        conversation: "Conversation",
        session_manager: "SessionManager",
        interface: "SolveigInterface",
        msg_index: int,
        part_index: int,
        role: Literal["user", "assistant"],
    ):
        super().__init__(comment)
        self.conversation = conversation
        self.session_manager = session_manager
        self.interface = interface
        self.msg_index = msg_index
        self.part_index = part_index
        self.role = role

    def compose(self):
        yield Markdown(f"🗩 ⠀{self.comment}")
        yield CopyButton(self.comment)
        yield EditButton(self)
        if self.role == "user":
            yield RetryButton(self)
        yield DeleteButton(self)
        yield BranchButton(self)

    async def begin_edit(self) -> None:
        try:
            new_text = await self.interface.ask_question(
                "Edit message:", default=self.comment
            )
        except UserCancel:
            return
        self.conversation.edit_part(self.msg_index, self.part_index, new_text)
        self.comment = new_text
        await self.query_one(Markdown).update(f"🗩 ⠀{self.comment}")

    async def retry(self) -> None:
        text = self.comment
        self.conversation.delete_from(self.msg_index)
        self._schedule_redraw()
        await self.interface.pending_queue.put(text)
        await self.interface.notify_pending_queue_changed()

    async def delete_from_here(self) -> None:
        self.conversation.delete_from(self.msg_index)
        self._schedule_redraw()

    async def branch_from_here(self) -> None:
        await self.session_manager.store(self.conversation)
        self.conversation.delete_from(self.msg_index)
        self._schedule_redraw()

    def _schedule_redraw(self) -> None:
        """Clear and replay the conversation as a separate task.

        This is called from a click handler on a widget that's about to be
        removed (self is a descendant of the conversation area being
        cleared) - awaiting the removal inline, in that same call stack,
        deadlocks Textual's message pump. Scheduling it as an independent
        task lets the current click handler return first."""
        asyncio.create_task(self._redraw())

    async def _redraw(self) -> None:
        await self.interface.clear_conversation()
        await self.session_manager.redraw(self.conversation, self.interface)


class CopyButton(Static):
    """A small clickable widget that copies text to the clipboard."""

    def __init__(self, content: str | Callable[[], str], **kwargs):
        super().__init__("⧉ Copy", markup=False, classes="copy-button")
        self._copy_content = content

    @property
    def copy_content(self):
        return (
            self._copy_content()
            if isinstance(self._copy_content, Callable)
            else self._copy_content
        )

    def on_click(self, event: Click) -> None:
        event.stop()
        # Copy to clipboard
        copy_to_clipboard(self.copy_content)
        # Display a success message for 1s
        _content = self.content
        self.update("✓ Copied!")
        self.set_timer(1.0, lambda: self.update(_content))

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        return f"""
        CopyButton {{
            color: {theme.text};
            text-align: right;
            padding: 0 1;
            height: 1;
        }}

        CopyButton:hover {{
            color: {theme.section};
        }}
        """


class TextBox(Widget):
    """A text block widget with optional title and border."""

    def __init__(self, content: str | Syntax, title: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._content = content
        if title:
            self.border_title = title
        self.add_class("text_block")
        # self._scroll_end = scroll_end

    def compose(self):
        raw = self._content if isinstance(self._content, str) else self._content.code
        yield Static(self._content, markup=False)
        yield CopyButton(raw)

    def append(self, line: str) -> None:
        """Append a line to the box, refresh the display, and scroll the parent to end."""
        if isinstance(self._content, str):
            self._content += line
        else:
            self._content = line
        try:
            self.query_one(Static).update(self._content)
            self.query_one(CopyButton)._copy_content = self._content
        except Exception:
            pass
        self.refresh(layout=True)
        parent = self.parent
        while parent is not None:
            if isinstance(parent, ScrollableContainer):
                parent.scroll_end(animate=False)
                parent.call_after_refresh(parent.scroll_end)
            if parent.id == "conversation":
                break
            parent = parent.parent

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        """Generate CSS for TextBox."""
        return f"""
        TextBox {{
            border: solid {theme.box};
            margin: 1;
            padding: 0 1;
            height: auto;
        }}

        {CopyButton.get_css(theme)}
        """


class SectionHeader(Static):
    """A section header with responsive line extending to the right."""

    def __init__(self, title: str):
        self._title = title
        super().__init__("")

    def on_mount(self):
        """Update content when first mounted."""
        self._update_content()

    def on_resize(self):
        """Recalculate line when terminal resizes."""
        self._update_content()

    def _update_content(self):
        """Generate section line based on current width.

        Note: This recalculates on every resize event. We explored alternatives:
        - Textual's Rule widget (designed for separators, not inline decorative fills)
        - CSS border-bottom (creates line below text, not alongside)
        - Horizontal container with fill (can't dynamically fill with repeating characters)

        Event-driven recalculation is the most Textual-native approach for this pattern.
        Performance impact is negligible - resize events are infrequent and calculation is cheap.
        """
        # Use this widget's own rendered width, not the parent's - the parent
        # doesn't account for this widget's margin or a reserved scrollbar
        # gutter, both of which shrink the space actually available here.
        width = self.size.width or 80

        header = f"━━━━ {self._title} "
        # Over-fill rather than compute an exact count and let CSS
        # text-overflow: clip trim the excess - the run of "━" has no
        # spaces, so Rich would otherwise treat it as one unbreakable word
        # and wrap the whole thing to a new row if the count is ever off by
        # even one character.
        line = "━" * width
        self.update(f"{header}{line}")

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        """Generate CSS for SectionHeader."""
        return f"""
        SectionHeader {{
            color: {theme.section};
            text-style: bold;
            margin: 0;
            text-wrap: nowrap;
            text-overflow: clip;
        }}
        """
