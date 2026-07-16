"""Message action buttons - Edit / Retry / Delete / Branch.

Each button owns a reference to the message widget it's attached to and,
on click, calls one method on that owner. No shared dispatch mechanism -
swap a button's behavior by editing its `on_click` override.
"""

from textual.events import Click
from textual.widgets import Static

from solveig.interface.base import EditableMessage
from solveig.interface.themes import Palette


class MessageButton(Static):
    """A clickable label owned by a message widget."""

    def __init__(self, owner: EditableMessage, label: str, **kwargs):
        super().__init__(label, markup=False, classes="message-button")
        self.owner = owner

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        return f"""
        MessageButton {{
            color: {theme.text};
            text-align: right;
            padding: 0 1;
            height: 1;
        }}

        MessageButton:hover {{
            color: {theme.section};
        }}
        """


class EditButton(MessageButton):
    def __init__(self, owner: EditableMessage, **kwargs):
        super().__init__(owner, "✎ Edit", **kwargs)

    async def on_click(self, event: Click) -> None:
        event.stop()
        await self.owner.begin_edit()


class RetryButton(MessageButton):
    def __init__(self, owner: EditableMessage, **kwargs):
        super().__init__(owner, "↻ Retry", **kwargs)

    async def on_click(self, event: Click) -> None:
        event.stop()
        await self.owner.retry()


class DeleteButton(MessageButton):
    def __init__(self, owner: EditableMessage, **kwargs):
        super().__init__(owner, "✕ Delete", **kwargs)

    async def on_click(self, event: Click) -> None:
        event.stop()
        await self.owner.delete_from_here()


class BranchButton(MessageButton):
    def __init__(self, owner: EditableMessage, **kwargs):
        super().__init__(owner, "⑂ Branch", **kwargs)

    async def on_click(self, event: Click) -> None:
        event.stop()
        await self.owner.branch_from_here()
