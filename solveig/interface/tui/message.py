"""Basic UI widgets for the Textual interface."""

from __future__ import annotations

from textual.containers import Horizontal
from textual.widgets import Markdown, Static

from solveig.exceptions import UserCancel
from solveig.interface.base import MessageBox, SolveigInterface
from solveig.interface.base.actions import MessageActions, Role

from .button import (
    BranchButton,
    Button,
    CopyButton,
    DeleteButton,
    EditButton,
    RetryButton,
)
from .collapsible import TextBoxWidget


class EditableComment(Static):
    """
    One drawn message: its text, and the actions it was handed.

    Buttons are rendered only for existing actions, including Copy
    which is a frontend-only concern. Uses background color based
    on the message's role.

    NOTE: a Textual widget cannot inherit a Protocol due to unrelated
    metaclasses, so `EditableComment` satisfies the `EditableMessage`
    protocol structurally.
    """

    def __init__(
        self,
        comment: str,
        *,
        interface: SolveigInterface,
        role: Role,
        actions: MessageActions,
    ):
        # NOTE: no CONTENT is handed up - the text is drawn by the Markdown
        # child in compose(), and passing it to `Static` too would render it
        # twice, once unstyled behind the other. The base initializer itself
        # still has to run: `Static.__init__` is what sets its `__content`/
        # `__visual` privates, and a widget that skips it renders once and then
        # dies inside `Static.visual` the first time it is drawn.
        super().__init__()
        self.comment = comment
        self.interface = interface
        self.role = role
        self.actions = actions
        # The role decides the inset and the tint, and nothing else: which
        # buttons appear is decided by which actions arrived.
        self.add_class(f"role-{role}")

        # Create a button per existing message action (plus copy)
        self._buttons: list[Button] = [CopyButton(lambda: self.comment)]
        _actions = [
            (self.actions.edit, EditButton),
            (self.actions.retry, RetryButton),
            (self.actions.branch, BranchButton),
            (self.actions.delete, DeleteButton),
        ]
        for action, button_cls in _actions:
            if action is not None:
                self._buttons.append(button_cls(self))

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
                yield from self._buttons

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

    DEFAULT_CSS = """
        EditableComment {
            margin: 1;
        }

        /* Increase left-padding for user comments */
        EditableComment.role-user {
            margin: 2 1 2 12;
        }

        /* Set Markdown background for user comments */
        EditableComment.role-user > Markdown {
            background: $background-user;
            padding: 0 1;
        }

        /* Actions buttons for user comments align to the right */
        EditableComment.role-user .comment-actions-row {
            align-horizontal: right;
        }

        MarkdownBlock:last-of-type {
            margin-bottom: 0;
        }

        .comment-actions-row {
            width: 100%;
            height: auto;
        }

        .comment-actions {
            width: auto;
            height: auto;
            border-top: solid $border;
        }
        """


class CommentBox(MessageBox):
    """A drawn conversational turn."""

    def __init__(self, widget: EditableComment) -> None:
        self.widget = widget

    async def replace(self, text: str) -> None:
        # `comment` is what the Copy button and the edit prompt read, so it has
        # to move with the rendered text or the two disagree after an edit.
        self.widget.comment = text
        for markdown in self.widget.query(Markdown):
            await markdown.update(f"🗩 ⠀{text}")
            break

    async def remove(self) -> None:
        await self.widget.remove()


class ReasoningBox(MessageBox):
    """A drawn reasoning block: no role, no actions, folded away by default."""

    def __init__(self, widget: TextBoxWidget) -> None:
        self.widget = widget

    async def replace(self, text: str) -> None:
        self.widget.update_content(text)

    async def remove(self) -> None:
        await self.widget.remove()
