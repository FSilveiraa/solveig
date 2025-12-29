"""Basic UI widgets for the Textual CLI interface."""

from rich.syntax import Syntax
from textual.widget import Widget
from textual.widgets import Collapsible, Static

from solveig.interface.cli.collapsible_widgets import CustomCollapsibleTitleBar


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
            title="",  # Empty title, will be replaced with custom one
            collapsed=self._collapsed,
        )

        # Replace default title with CustomCollapsibleTitleBar
        self._collapsible._title = CustomCollapsibleTitleBar(
            collapsed_text=f"{self._title} - Click to expand",
            expanded_text=f"{self._title} - Click to collapse",
            start_collapsed=self._collapsed,
        )

        with self._collapsible:
            yield Static(
                self._content,
                markup=False,
                classes=self._content_classes,
            )


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
        """Generate section line based on current width."""
        # Get parent width, fallback to 80
        try:
            width = self.parent.size.width if self.parent else 80
        except AttributeError:
            width = 80

        header = f"━━━━ {self._title}"
        remaining = max(0, width - len(header) - 2)
        line = "━" * remaining
        self.update(f"{header} {line}")
