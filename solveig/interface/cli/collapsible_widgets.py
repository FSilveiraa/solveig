"""Reusable collapsible widget components for Textual UI.

This module provides base collapsible widgets that can be used throughout the application
for any content that needs to be expandable/collapsible (stats, reasoning, logs, etc.).
"""

from textual.containers import Horizontal
from textual.widgets import Collapsible, Static
from textual.widgets._collapsible import CollapsibleTitle

from solveig.interface.themes import Palette


class DividedCollapsibleTitleBar(CollapsibleTitle):
    """Custom title bar with responsive left/center/right layout.

    This title bar is designed for use with CustomCollapsible and supports
    dynamic content in three sections (left, center, right) that update
    when the collapsed state changes.
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
        # CollapsibleTitle requires these parameters
        self._collapsed_text = collapsed_text
        self._expanded_text = expanded_text
        self._status = status
        self._path = path
        self._theme = theme
        super().__init__(
            label="",
            collapsed_symbol="▶",
            expanded_symbol="▼",
            collapsed=start_collapsed,
        )

    def compose(self):
        """Override to yield three Static widgets instead of string content."""
        left_content, center_content, right_content = self._get_content()

        yield Horizontal(
            Static(left_content, classes="title-left"),
            Static(center_content, classes="title-center"),
            Static(right_content, classes="title-right"),
            classes="custom-title-bar",
        )

    def _watch_collapsed(self, collapsed: bool) -> None:
        """Override to update our Static widgets when collapsed state changes."""
        self._update_static_widgets()

    def _get_content(self):
        """Generate content for the three title sections."""
        if self.collapsed:
            left_content = f"{self.collapsed_symbol} {self._collapsed_text}"
        else:
            left_content = f"{self.expanded_symbol} {self._expanded_text}"

        center_content = f"[{self._theme.info}]{self._status}[/]"
        right_content = f"🗁  {self._path}"
        return left_content, center_content, right_content

    def _update_static_widgets(self):
        """Update the Static widgets with current content and symbol."""
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

        self._update_static_widgets()


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
