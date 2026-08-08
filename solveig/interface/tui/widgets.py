"""Basic UI widgets for the Textual interface."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.events import Click
from textual.widgets import Markdown, Static

from solveig.exceptions import UserCancel
from solveig.interface.base.actions import MessageActions, Role
from solveig.utils.misc import copy_to_clipboard

from .buttons import BranchButton, DeleteButton, EditButton, RetryButton

if TYPE_CHECKING:
    from solveig.interface.base import SolveigInterface


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
    """A Comment that offers the actions it was handed.

    It knows the text, who said it, and what may be done to it - not which
    message it is, nor that a conversation exists. Every button below is
    rendered because an action for it arrived; "an assistant turn cannot be
    retried" is expressed by no retry action being handed over, not by this
    widget re-deriving the rule from a role.

    Satisfies the `EditableMessage` protocol structurally — a Textual widget
    cannot inherit a Protocol (unrelated metaclasses). The buttons below
    declare `owner: EditableMessage`, so a missing method fails there."""

    def __init__(
        self,
        comment: str,
        *,
        interface: "SolveigInterface",
        role: Role,
        actions: MessageActions,
    ):
        super().__init__(comment)
        self.interface = interface
        self.role = role
        self.actions = actions
        # Role class carries the section tint (user turns get a lighter band),
        # now that comments mount flat rather than inside a tinted container.
        self.add_class(f"role-{role}")

    def compose(self):
        yield Markdown(f"🗩 ⠀{self.comment}")
        # Action buttons share one horizontal row, separated from the message
        # text above by a top border (see .comment-actions in Comment.get_css).
        with Horizontal(classes="comment-actions"):
            yield CopyButton(lambda: self.comment)
            if self.actions.edit is not None:
                yield EditButton(self)
            if self.actions.retry is not None:
                yield RetryButton(self)
            if self.actions.delete is not None:
                yield DeleteButton(self)
            if self.actions.branch is not None:
                yield BranchButton(self)

    async def begin_edit(self) -> None:
        """Collect the new text - HOW to ask is this frontend's alone - and
        hand it over. What an edit then means is the app's business, including
        whether it is allowed right now."""
        if self.actions.edit is None:
            return
        try:
            new_text = await self.interface.ask_question(
                "Edit message:", default=self.comment
            )
        except UserCancel:
            return
        await self.actions.edit(new_text)

    async def retry(self) -> None:
        if self.actions.retry is not None:
            await self.actions.retry()

    async def delete_from_here(self) -> None:
        if self.actions.delete is not None:
            await self.actions.delete()

    async def branch_from_here(self) -> None:
        if self.actions.branch is not None:
            await self.actions.branch()


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
