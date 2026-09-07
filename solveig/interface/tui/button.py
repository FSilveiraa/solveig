"""
Each button has
Each button owns a reference to the message widget it's attached to and,
on click, calls one method on that owner. No shared dispatch mechanism -
swap a button's behavior by editing its `on_click` override.
"""
import asyncio
from collections.abc import Callable
from typing import override, Self

from textual.widgets import Button as _Button

from solveig.interface.base import EditableMessage
from solveig.utils.misc import copy_to_clipboard


class Button(_Button):
    """A clickable label owned by a message widget."""
    LABEL: str
    DOING_LABEL: str | None = None
    DONE_LABEL: str | None = None
    DONE_LABEL_SECONDS = 1.0

    DEFAULT_CSS = """
        Button {
            color: $foreground;
            /* width: auto so each button is only as wide as its label, packing
               left-to-right in the action row instead of each taking full width. */
            width: auto;
            padding: 0 1;
            height: 1;
        }

        Button:hover {
            color: $accent;
        }
    """

    def __init__(self, label: str | None = None):
        super().__init__(label=label or self.LABEL)

    async def _act(self) -> None:
        """The actual async work to be accomplished by this button.."""
        ...

    def press(self) -> Self:
        """
        Schedules an async action and flashes a success on the button when done.

        This button callback is synchronous, so it can't run async callbacks.
        `asyncio.create_task/ensure_future` conflict with the Textual thread.
        `call_after_refresh` schedules after frame computing has finished.

        NOTE: consider an optionally-async `press` as a PR to Textual.
        """
        self.call_after_refresh(self._act_in_background)
        return super().press()

    async def _act_in_background(self) -> None:
        self.disabled = True
        try:
            if self.DOING_LABEL:
                self.label = self.DOING_LABEL
            await self._act()
        finally:
            # The widget itself may be gone from the DOM,
            #  like in retry/delete/branch
            if self.is_mounted:
                self.disabled = False
                self.label = self.LABEL
        if self.DONE_LABEL is not None:
            self.call_after_refresh(self._display_done)

    async def _display_done(self) -> None:
        assert self.DONE_LABEL is not None
        self.label = self.DONE_LABEL
        await asyncio.sleep(self.DONE_LABEL_SECONDS)
        self.label = self.LABEL


class MessageButton(Button):
    def __init__(self, message: EditableMessage, label: str | None = None):
        super().__init__(label)
        self.message = message


class CopyButton(Button):
    LABEL = "⧉ Copy"
    DONE_LABEL = "✓ Copied!"

    def __init__(self, content: str | Callable[[], str]):
        super().__init__()
        self._content = content

    @property
    def content(self) -> str:
        if isinstance(self._content, str):
            return self._content
        return self._content()

    @override
    async def _act(self) -> None:
        copy_to_clipboard(self.content)


class EditButton(MessageButton):
    LABEL = "✎ Edit"
    DOING_LABEL = "… Editing"
    DONE_LABEL = "✓ Edited!"

    @override
    async def _act(self) -> None:
        await self.message.begin_edit()


class RetryButton(MessageButton):
    LABEL = "↻ Retry"
    DOING_LABEL = "… Retrying"
    DONE_LABEL = "✓ Retried!"

    @override
    async def _act(self) -> None:
        await self.message.retry()


class DeleteButton(MessageButton):
    LABEL = "✕ Delete"

    @override
    async def _act(self) -> None:
        await self.message.delete_from_here()


class BranchButton(MessageButton):
    LABEL = "⑂ Branch"

    @override
    async def _act(self) -> None:
        await self.message.branch_from_here()
