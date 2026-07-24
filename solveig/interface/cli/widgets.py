"""Basic UI widgets for the Textual CLI interface."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from textual.containers import Horizontal
from textual.events import Click
from textual.widgets import Markdown, Static

from solveig.exceptions import UserCancel
from solveig.interface.base import EditableMessage
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
    def get_css(cls) -> str:
        return """
        .text_comment {
            /* Section content: 1 on all four sides. Vertically this collapses
               (max) with neighbours - a section header's top-2 wins at a
               section boundary, giving 2 between sections and 1 within. */
            margin: 1;
        }

        Markdown {
            color: $foreground;
            padding: 0;
        }

        MarkdownBlock:last-of-type {
            margin-bottom: 0;
        }

        /* Action buttons on one row, with a top border (in the box-border
           colour) separating them from the message text above. width: auto so
           the row - and its separator border - is only as wide as the buttons,
           not the full comment; height: auto so it's just the 1-row buttons. */
        .comment-actions {
            width: auto;
            height: auto;
            border-top: solid $box;
        }

        /* Each button only as wide as its label, so they pack left-to-right
           in the row. (MessageButton is action-row-only and set globally; the
           shared CopyButton is scoped here so box/title-bar copies keep their
           own right-alignment.) */
        .comment-actions CopyButton {
            width: auto;
        }
        """


class EditableComment(Comment, EditableMessage):
    """A Comment tied to a conversation message by its stable `message_id`
    (and the `part_index` within it), with Edit/Retry/Delete/Branch action
    buttons. Mutations go through the Conversation by id; the reactive
    transcript reconciles the displayed widgets in place - the widget never
    redraws the conversation itself. Retry only makes sense for user turns -
    regenerating an assistant response is Edit+Retry on the preceding user
    message instead."""

    def __init__(
        self,
        comment: str,
        *,
        conversation: "Conversation",
        session_manager: "SessionManager",
        interface: "SolveigInterface",
        message_id: str,
        part_index: int,
        role: Literal["user", "assistant"],
    ):
        super().__init__(comment)
        self.conversation = conversation
        self.session_manager = session_manager
        self.interface = interface
        self.message_id = message_id
        self.part_index = part_index
        self.role = role
        # Role class carries the section tint (user turns get a lighter band),
        # now that comments mount flat rather than inside a tinted container.
        self.add_class(f"role-{role}")

    def compose(self):
        yield Markdown(f"🗩 ⠀{self.comment}")
        # Action buttons share one horizontal row, separated from the message
        # text above by a top border (see .comment-actions in Comment.get_css).
        with Horizontal(classes="comment-actions"):
            yield CopyButton(lambda: self.comment)
            yield EditButton(self)
            if self.role == "user":
                yield RetryButton(self)
            yield DeleteButton(self)
            yield BranchButton(self)

    async def _flash_finish_run_first(self) -> None:
        """Explain why a click was ignored: a history mutation mid-run is
        reconciled away when adopt() re-syncs the conversation at run end, and
        a mid-run retry would be drained into the running turn as an
        interjection instead of starting fresh."""
        await self.interface.update_stats(
            status="Finish or cancel the current run first", duration=3
        )

    async def begin_edit(self) -> None:
        if self.interface.get_active_tasks():
            await self._flash_finish_run_first()
            return
        try:
            new_text = await self.interface.ask_question(
                "Edit message:", default=self.comment
            )
        except UserCancel:
            return
        self.comment = new_text
        await self.conversation.edit(self.message_id, self.part_index, new_text)

    async def retry(self) -> None:
        if self.interface.get_active_tasks():
            await self._flash_finish_run_first()
            return
        text = self.comment
        await self.conversation.truncate_from(self.message_id)
        # Resubmit through the app's producer callback - the same path typed
        # input takes (command routing + the session UserMessageQueue).
        if self.interface.on_user_input is not None:
            await self.interface.on_user_input(self.interface, text)

    async def delete_from_here(self) -> None:
        if self.interface.get_active_tasks():
            await self._flash_finish_run_first()
            return
        await self.conversation.truncate_from(self.message_id)

    async def branch_from_here(self) -> None:
        if self.interface.get_active_tasks():
            await self._flash_finish_run_first()
            return
        await self.session_manager.checkpoint(self.conversation)
        await self.conversation.truncate_from(self.message_id)


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
    def get_css(cls) -> str:
        return """
        CopyButton {
            color: $foreground;
            text-align: right;
            padding: 0 1;
            height: 1;
        }

        CopyButton:hover {
            color: $section;
        }
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

        NOTE: Recalculated on every resize (cheap; resize events are rare).
        Rule/border-bottom/fill-container were all rejected - none does an inline
        decorative fill alongside text.
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
    def get_css(cls) -> str:
        """Generate CSS for SectionHeader."""
        return """
        SectionHeader {
            color: $section;
            text-style: bold;
            /* Spacing model: 2 rows above a section, 1 below. Textual collapses
               adjacent sibling margins to the max, so this composes with the
               1/1 margins on comments/boxes/groups to give "2 above sections,
               1 everywhere else" without ever stacking. */
            margin: 2 0 1 0;
            text-wrap: nowrap;
            text-overflow: clip;
        }

        /* No leading gap at the very top of the scroll. */
        SectionHeader:first-of-type {
            margin-top: 0;
        }
        """
