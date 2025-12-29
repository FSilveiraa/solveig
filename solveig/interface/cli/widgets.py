"""Basic UI widgets for the Textual CLI interface."""

from rich.syntax import Syntax
from textual.widget import Widget
from textual.widgets import Collapsible, Static


class TextBox(Static):
    """A text block widget with optional title and border."""

    def __init__(self, content: str | Syntax, title: str | None = None, **kwargs):
        super().__init__(content, markup=False, **kwargs)
        self.border = "solid"
        if title:
            self.border_title = title
        self.add_class("text_block")


class CollapsibleTextBox(Widget):
    """A collapsible text block widget for reasoning, verbose output, etc.

    Similar to StatsBar pattern - a Widget that contains a Collapsible.
    Provides click-to-toggle functionality for long text content.
    """

    def __init__(
        self,
        content: str | Syntax,
        title: str,
        collapsed: bool = False,
        content_classes: str = "reasoning-content",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._content = content
        self._content_classes = content_classes
        self._title = title
        self._collapsed = collapsed

    def compose(self):
        """Yield a Collapsible containing the content - like StatsBar pattern."""
        self._collapsible = Collapsible(
            title=self._title,
            collapsed=self._collapsed,
            collapsed_symbol="▶",
            expanded_symbol="▼",
        )

        with self._collapsible:
            yield Static(
                self._content,
                markup=False,
                classes=self._content_classes,
            )


class SectionHeader(Static):
    """A section header widget with line extending to the right."""

    def __init__(self, title: str, width: int = 80):
        # Calculate the line with dashes
        # Create the section line
        header_prefix = f"━━━━ {title}"
        remaining_width = width - len(header_prefix) - 3
        dashes = "━" * max(0, remaining_width)

        section_line = f"{header_prefix} {dashes}"
        super().__init__(section_line)
        self.add_class("section_header")
