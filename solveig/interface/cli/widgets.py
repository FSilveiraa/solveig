"""Basic UI widgets for the Textual CLI interface."""

from collections.abc import Callable

from rich.syntax import Syntax
from textual.containers import ScrollableContainer
from textual.events import Click
from textual.widget import Widget
from textual.widgets import Markdown, Static

from solveig.interface.themes import Palette
from solveig.utils.misc import copy_to_clipboard


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
        # Get parent width, fallback to 80
        try:
            width = self.parent.size.width if self.parent else 80
        except AttributeError:
            width = 80

        header = f"━━━━ {self._title}"
        remaining = max(0, width - len(header) - 2)
        line = "━" * remaining
        self.update(f"{header} {line}")

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        """Generate CSS for SectionHeader."""
        return f"""
        SectionHeader {{
            color: {theme.section};
            text-style: bold;
            margin: 2 0 1 0;
        }}
        """
