"""Reusable collapsible widget components for Textual UI.

This module provides base collapsible widgets that can be used throughout the application
for any content that needs to be expandable/collapsible (stats, reasoning, logs, etc.).
"""

from rich.syntax import Syntax
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Collapsible, Static
from textual.widgets._collapsible import CollapsibleTitle

from solveig.interface.themes import Palette


class CustomCollapsibleTitleBar(CollapsibleTitle):
    """Base class for custom collapsible title bars.

    Provides automatic symbol (▶/▼) and text updates when collapsed state changes.
    All custom collapsibles have "click to expand/collapse" text functionality.

    This simple implementation shows symbol + text in a single section.
    Subclasses can override to create more complex multi-section layouts.
    """

    def __init__(
        self,
        collapsed_text: str,
        expanded_text: str,
        start_collapsed: bool = True,
    ):
        self._collapsed_text = collapsed_text
        self._expanded_text = expanded_text
        super().__init__(
            label="",
            collapsed_symbol="▶",
            expanded_symbol="▼",
            collapsed=start_collapsed,
        )

    def compose(self):
        """Yield single Static widget with symbol + text."""
        yield Static(self._get_content(), classes="simple-title")

    def _get_content(self):
        """Generate symbol + text based on collapsed state."""
        if self.collapsed:
            return f"{self.collapsed_symbol} {self._collapsed_text}"
        else:
            return f"{self.expanded_symbol} {self._expanded_text}"

    def _watch_collapsed(self, collapsed: bool) -> None:
        """When collapsed state changes, update the display."""
        self._update_content()

    def _update_content(self):
        """Update the Static widget with current content."""
        try:
            static = self.query_one(Static)
            static.update(self._get_content())
        except NoMatches:
            # Widget not mounted yet - will update when compose() completes
            pass


class DividedCollapsibleTitleBar(CollapsibleTitle):
    """3-section title bar with left/center/right content areas.

    Layout: left (symbol + text) | center | right

    Generic container that can be used for any purpose - stats, logs,
    reasoning display, etc. Each section can be independently updated.
    """

    def __init__(
        self,
        left: str,
        center: str = "",
        right: str = "",
        collapsed_symbol: str = "▶",
        expanded_symbol: str = "▼",
        start_collapsed: bool = True,
    ):
        self._left = left
        self._center = center
        self._right = right
        self._collapsed_symbol = collapsed_symbol
        self._expanded_symbol = expanded_symbol
        super().__init__(
            label="",
            collapsed_symbol=collapsed_symbol,
            expanded_symbol=expanded_symbol,
            collapsed=start_collapsed,
        )

    def compose(self):
        """Yield 3-section layout."""
        left_content, center_content, right_content = self._get_content()

        yield Horizontal(
            Static(left_content, classes="title-left"),
            Static(center_content, classes="title-center"),
            Static(right_content, classes="title-right"),
            classes="custom-title-bar",
        )

    def _get_content(self):
        """Generate content for all 3 sections based on collapsed state."""
        symbol = self._collapsed_symbol if self.collapsed else self._expanded_symbol
        left_content = f"{symbol} {self._left}"
        return left_content, self._center, self._right

    def _watch_collapsed(self, collapsed: bool) -> None:
        """Update display when collapsed state changes."""
        self._update_content()

    def _update_content(self):
        """Update all 3 static widgets."""
        try:
            horizontal = self.query_one(Horizontal)
            statics = horizontal.query(Static)
            left_content, center_content, right_content = self._get_content()

            statics[0].update(left_content)
            statics[1].update(center_content)
            statics[2].update(right_content)
        except NoMatches:
            pass

    def update_sections(
        self,
        left: str | None = None,
        center: str | None = None,
        right: str | None = None,
    ):
        """Update any or all sections of the title bar.

        Args:
            left: New content for left section (includes symbol)
            center: New content for center section
            right: New content for right section
        """
        if left is not None:
            self._left = left
        if center is not None:
            self._center = center
        if right is not None:
            self._right = right
        self._update_content()

    def update_symbols(
        self,
        collapsed: str | None = None,
        expanded: str | None = None,
    ):
        """Update the collapse/expand symbols.

        Args:
            collapsed: Symbol shown when collapsed (default: ▶)
            expanded: Symbol shown when expanded (default: ▼)
        """
        if collapsed is not None:
            self._collapsed_symbol = collapsed
        if expanded is not None:
            self._expanded_symbol = expanded
        self._update_content()


class CustomCollapsible(Collapsible):
    """Collapsible with custom three-section title bar.

    Provides a reusable base for any widget that needs collapsible functionality
    with left/center/right sections that can be independently updated.
    """

    def __init__(
        self,
        left: str,
        center: str = "",
        right: str = "",
        collapsed_symbol: str = "▶",
        expanded_symbol: str = "▼",
        start_collapsed: bool = True,
        **kwargs,
    ):
        super().__init__(title="", collapsed=start_collapsed, **kwargs)
        # Replace the _title widget with our custom one
        self._title: DividedCollapsibleTitleBar = DividedCollapsibleTitleBar(
            left=left,
            center=center,
            right=right,
            collapsed_symbol=collapsed_symbol,
            expanded_symbol=expanded_symbol,
            start_collapsed=start_collapsed,
        )

    def update_sections(
        self,
        left: str | None = None,
        center: str | None = None,
        right: str | None = None,
    ):
        """Update any section(s) of the title bar.

        Args:
            left: New content for left section
            center: New content for center section
            right: New content for right section
        """
        self._title.update_sections(left=left, center=center, right=right)


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

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        """Generate CSS for CollapsibleTextBox."""
        return f"""
        CollapsibleTextBox {{
            margin: 0 0 0 1;
            padding: 0;
            height: auto;
            border: solid {theme.box};
            background: {theme.background};
        }}

        CollapsibleTextBox Collapsible {{
            background: {theme.background};
            border: none;
            margin: 0;
            padding: 0;
        }}

        CollapsibleTextBox CollapsibleTitle {{
            background: {theme.background};
            padding: 0;
            height: auto;
        }}

        CollapsibleTextBox .simple-title {{
            background: {theme.background};
            color: {theme.text};
            padding: 0 1;
            height: 1;
        }}

        CollapsibleTextBox .simple-title:hover {{
            color: {theme.section};
        }}

        .reasoning-content {{
            text-style: italic;
            color: {theme.text};
            height: auto;
            padding: 0 1;
            background: {theme.background};
        }}
        """
