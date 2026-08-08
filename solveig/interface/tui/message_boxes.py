"""The handles `add_message` and `add_reasoning` hand back.

Each owns the widget it drew and exposes the two things a transcript ever does
to a message it already put on screen: restate it, or take it back. Owning a
widget rather than being one is the same rule the other box handles follow -
handing a Textual widget across the protocol would give app code `.mount()`,
`.parent` and the rest of the framework under a name that promises two methods.

There is no map from message id to widget here, and no class that keeps one.
The handle IS the identity, so the observer that added a message is the only
thing that remembers it - which is what lets this file know nothing about
conversations, ids or parts.
"""

from __future__ import annotations

from textual.widgets import Markdown as MarkdownWidget

from solveig.interface.base.widgets import MessageBox

from .collapsible_widgets import TextBoxWidget
from .widgets import EditableComment


class CommentBox(MessageBox):
    """A drawn conversational turn."""

    def __init__(self, widget: EditableComment) -> None:
        self.widget = widget

    async def replace(self, text: str) -> None:
        # `comment` is what the Copy button and the edit prompt read, so it has
        # to move with the rendered text or the two disagree after an edit.
        self.widget.comment = text
        for markdown in self.widget.query(MarkdownWidget):
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
