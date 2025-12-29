"""Reusable collapsible widget components for Textual UI.

This module provides base collapsible widgets that can be used throughout the application
for any content that needs to be expandable/collapsible (stats, reasoning, logs, etc.).
"""

from textual.containers import Horizontal
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
        except Exception:
            # If not mounted yet, will update when it mounts
            pass


class DividedCollapsibleTitleBar(CustomCollapsibleTitleBar):
    """3-section title bar extending CustomCollapsibleTitleBar.

    Layout: left (symbol + text) | center (status) | right (path)

    Used by StatsBar for displaying dynamic status and path alongside
    the collapsible text.
    """

    def __init__(
        self,
        collapsed_text: str,
        expanded_text: str,
        status: str,
        path: str,
        theme: Palette,
        start_collapsed: bool = True,
    ):
        self._status = status
        self._path = path
        self._theme = theme
        # Call parent to set up collapsed/expanded text and symbols
        super().__init__(
            collapsed_text=collapsed_text,
            expanded_text=expanded_text,
            start_collapsed=start_collapsed,
        )

    def compose(self):
        """Override to yield 3-section layout instead of simple single section."""
        left_content, center_content, right_content = self._get_content()

        yield Horizontal(
            Static(left_content, classes="title-left"),
            Static(center_content, classes="title-center"),
            Static(right_content, classes="title-right"),
            classes="custom-title-bar",
        )

    def _get_content(self):
        """Override to return 3 sections: (left_with_symbol, center_status, right_path)."""
        # Get symbol + text from parent logic
        if self.collapsed:
            left_content = f"{self.collapsed_symbol} {self._collapsed_text}"
        else:
            left_content = f"{self.expanded_symbol} {self._expanded_text}"

        # Add the extra sections specific to Divided
        center_content = f"[{self._theme.info}]{self._status}[/]"
        right_content = f"🗁  {self._path}"
        return left_content, center_content, right_content

    def _update_content(self):
        """Override to update 3 static widgets instead of 1."""
        try:
            horizontal = self.query_one(Horizontal)
            statics = horizontal.query(Static)
            left_content, center_content, right_content = self._get_content()

            statics[0].update(left_content)
            statics[1].update(center_content)
            statics[2].update(right_content)
        except Exception:
            # If not mounted yet, will update when it mounts
            pass

    def update_content(self, status=None, path=None):
        """Update the content of the title sections."""
        if status is not None:
            self._status = status
        if path is not None:
            self._path = path

        self._update_content()


class CustomCollapsible(Collapsible):
    """Collapsible with custom responsive title bar.

    This provides a reusable base for any widget that needs collapsible functionality
    with a custom three-section title bar (left, center, right).

    Used by StatsBar and can be extended for other collapsible widgets.
    """

    def __init__(
        self,
        collapsed_text: str,
        expanded_text: str,
        status: str,
        path: str,
        theme: Palette,
        start_collapsed: bool = True,
        **kwargs,
    ):
        super().__init__(title="", collapsed=start_collapsed, **kwargs)
        # Replace the _title widget with our custom one
        self._title = DividedCollapsibleTitleBar(
            collapsed_text=collapsed_text,
            expanded_text=expanded_text,
            status=status,
            path=path,
            theme=theme,
            start_collapsed=True,
        )

    def update_title_content(self, status_text=None, path_text=None):
        """Update the title bar content."""
        self._title.update_content(status_text, path_text)
