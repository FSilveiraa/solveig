"""Basic UI widgets for the Textual interface."""

from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.widgets import Markdown, Static

from solveig.exceptions import UserCancel
from solveig.interface.base.actions import MessageActions, Role

from .buttons import BranchButton, CopyButton, DeleteButton, EditButton, RetryButton

if TYPE_CHECKING:
    from solveig.interface.base import SolveigInterface


class EditableComment(Static):
    """One drawn message: its text, and the actions it was handed.

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
        # NOTE: no content passed up. This is a CONTAINER - the text is drawn by
        # the Markdown child in compose(). Handing it to Static as well would
        # render it twice, once unstyled behind the other.
        super().__init__()
        self.comment = comment
        self.interface = interface
        self.role = role
        self.actions = actions
        # The role decides the inset and the tint, and nothing else: which
        # buttons appear is decided by which actions arrived.
        self.add_class(f"role-{role}")

    def compose(self):
        yield Markdown(f"🗩 ⠀{self.comment}")
        # Two rows, not one: the outer is full width and decides WHERE the
        # buttons sit (a user turn puts them on the right), the inner is only
        # as wide as the buttons so its separator border is too. Alignment in
        # Textual moves a container's children as a group, so an auto-width row
        # cannot right-align itself against a full-width sibling - it needs a
        # full-width parent of its own to move inside.
        with Horizontal(classes="comment-actions-row"):
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

    @classmethod
    def get_css(cls) -> str:
        return """
        /* Every comment: 1 on all four sides. Vertically this collapses (max)
           with neighbours, so adjacent margins never stack. The role rules
           below override it - they are type+class, so they win on specificity
           without !important. */
        EditableComment {
            margin: 1;
        }

        /* The two turns lean on opposite sides, which is what makes a glance
           down the transcript readable: the shape says who is speaking before
           any colour does. Mirrored insets, so neither turn is the odd one.
           The user also gets 2 rows of vertical margin instead of 1 - their
           turn is where a reader looks to find the start of an exchange. */
        EditableComment.role-user {
            margin: 2 1 2 12;
        }

        /* The user's controls sit under the right edge of their own turn, so
           the eye follows one side of the transcript rather than crossing it. */
        EditableComment.role-user .comment-actions-row {
            align-horizontal: right;
        }

        EditableComment.role-assistant {
            margin: 1 12 1 1;
        }

        /* The tint is on the comment TEXT only, never the action buttons under
           it - so it goes on the Markdown child, not the whole comment. */
        EditableComment.role-user > Markdown {
            background: $user-turn-bg;
            padding: 0 1;
        }

        Markdown {
            color: $foreground;
            padding: 0;
        }

        MarkdownBlock:last-of-type {
            margin-bottom: 0;
        }

        /* Full width and no styling of its own: it exists only to give the
           button row room to sit somewhere other than hard left. */
        .comment-actions-row {
            width: 100%;
            height: auto;
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
