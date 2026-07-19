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
            /* width: auto so each button is only as wide as its label, packing
               left-to-right in the action row instead of each taking full width. */
            width: auto;
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


# Retry/Delete/Branch all truncate the conversation, which removes this button's
# own owner widget (and thus the button) from the tree. Doing that synchronously
# from within the button's own click handler is the "remove-during-own-event"
# trap: Textual can't finish unmounting a widget while its message pump is still
# running the handler, so the button is left stranded on screen (still showing
# its hover highlight). call_after_refresh defers the mutation to a Screen-owned
# callback that runs once the click has fully settled, so the removal is clean.
class RetryButton(MessageButton):
    def __init__(self, owner: EditableMessage, **kwargs):
        super().__init__(owner, "↻ Retry", **kwargs)

    def on_click(self, event: Click) -> None:
        event.stop()
        self.call_after_refresh(self.owner.retry)


class DeleteButton(MessageButton):
    def __init__(self, owner: EditableMessage, **kwargs):
        super().__init__(owner, "✕ Delete", **kwargs)

    def on_click(self, event: Click) -> None:
        event.stop()
        self.call_after_refresh(self.owner.delete_from_here)


class BranchButton(MessageButton):
    def __init__(self, owner: EditableMessage, **kwargs):
        super().__init__(owner, "⑂ Branch", **kwargs)

    def on_click(self, event: Click) -> None:
        event.stop()
        self.call_after_refresh(self.owner.branch_from_here)
