"""Basic UI widgets for the Textual CLI interface."""

from rich.syntax import Syntax
from textual.widgets import Static

from solveig.interface.themes import Palette


class TextBox(Static):
    """A text block widget with optional title and border."""

    def __init__(self, content: str | Syntax, title: str | None = None, **kwargs):
        super().__init__(content, markup=False, **kwargs)
        self.border = "solid"
        if title:
            self.border_title = title
        self.add_class("text_block")

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        """Generate CSS for TextBox."""
        return f"""
        TextBox {{
            border: solid {theme.box};
            margin: 1;
            padding: 0 1;
        }}
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
            margin: 1 0;
            padding: 0;
        }}
        """
