"""Basic UI widgets for the Textual interface."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.events import Click
from textual.widgets import Markdown, Static

from solveig.exceptions import UserCancel
from solveig.interface.base.actions import Role
from solveig.utils.misc import copy_to_clipboard

from .buttons import BranchButton, DeleteButton, EditButton, RetryButton

if TYPE_CHECKING:
    from solveig.interface.base import SolveigInterface
    from solveig.session.conversation import Conversation


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
            /* 1 on all four sides. Vertically this collapses (max) with
               neighbours, so adjacent margins never stack. */
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


class EditableComment(Comment):
    """A Comment tied to a conversation message by its stable `message_id`
    (and the `part_index` within it), with Edit/Retry/Delete/Branch action
    buttons. Mutations go through the Conversation by id; the reactive
    transcript reconciles the displayed widgets in place - the widget never
    redraws the conversation itself. Retry only makes sense for user turns -
    regenerating an assistant response is Edit+Retry on the preceding user
    message instead.

    Satisfies the `EditableMessage` protocol structurally — a Textual widget
    cannot inherit a Protocol (unrelated metaclasses). The buttons below
    declare `owner: EditableMessage`, so a missing method fails there."""

    def __init__(
        self,
        comment: str,
        *,
        conversation: "Conversation",
        interface: "SolveigInterface",
        message_id: str,
        part_index: int,
        role: Role,
    ):
        super().__init__(comment)
        self.conversation = conversation
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
            if self.role is Role.USER:
                yield RetryButton(self)
            yield DeleteButton(self)
            yield BranchButton(self)

    async def _flash_finish_run_first(self) -> None:
        """Explain why a click was ignored: a history mutation mid-run is
        reconciled away when adopt() re-syncs the conversation at run end, and
        a mid-run retry would be drained into the running turn as an
        interjection instead of starting fresh."""
        await self.interface.set_status(
            "Finish or cancel the current run first", duration=3
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
        # Resubmit through the session UserMessageQueue - the same path typed
        # input takes (prompt gate routes /commands before insertion).
        if self.interface.user_message_queue is not None:
            await self.interface.user_message_queue.put(text)

    async def delete_from_here(self) -> None:
        if self.interface.get_active_tasks():
            await self._flash_finish_run_first()
            return
        await self.conversation.truncate_from(self.message_id)

    async def branch_from_here(self) -> None:
        if self.interface.get_active_tasks():
            await self._flash_finish_run_first()
            return
        # `branch_from` rather than `truncate_from`: same rewind, different
        # event, so persistence can preserve what's being dropped. Whether that
        # means a file is written is none of this widget's business.
        await self.conversation.branch_from(self.message_id)


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
