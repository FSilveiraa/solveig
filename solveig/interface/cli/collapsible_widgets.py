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

from ..base import MutableTextBox
from .widgets import CopyButton


class DividedCollapsibleTitleBar(CollapsibleTitle):
    """3-section title bar: (symbol + left text) | center | right.

    Left text switches between left_collapsed/left_expanded based on state.
    Center and right accept str (rendered as Static) or any Widget.
    Widget sections are never overwritten by update_sections.
    """

    def __init__(
        self,
        left_collapsed: str | None,
        left_expanded: str | None,
        center: str | Widget = "",
        right: str | Widget = "",
        collapsed_symbol: str = "▶",
        expanded_symbol: str = "▼",
        start_collapsed: bool = True,
    ):
        self._left_collapsed = left_collapsed if left_collapsed is not None else "Show"
        self._left_expanded = left_expanded if left_expanded is not None else "Hide"
        self._center = center
        self._right = right
        super().__init__(
            label="",
            collapsed_symbol=collapsed_symbol,
            expanded_symbol=expanded_symbol,
            collapsed=start_collapsed,
        )

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        return f"""
        /* Custom title bar responsive layout */
        DividedCollapsibleTitleBar {{
            width: 100%;
            height: 1;
            color: {theme.text};
            background: {theme.background};
        }}

        .title-left {{
            text-align: left;
            width: 1fr;
        }}

        .title-left:hover {{
            color: {theme.section};
        }}

        .title-center {{
            text-align: center;
            width: auto;
        }}

        .title-right {{
            text-align: right;
            width: 1fr;
        }}
        """

    @property
    def _left(self) -> str:
        symbol = self.collapsed_symbol if self.collapsed else self.expanded_symbol
        text = self._left_collapsed if self.collapsed else self._left_expanded
        return f"{symbol} {text}"

    def compose(self):
        def _child(section: str | Widget, classes: str) -> Widget:
            if isinstance(section, str):
                return Static(section, classes=classes)
            else:
                section.add_class(classes)
                return section

        yield Horizontal(
            Static(self._left, classes="title-left"),
            _child(self._center, "title-center"),
            _child(self._right, "title-right"),
            classes="custom-title-bar",
        )

    def _update_label(self) -> None:
        pass  # We render via compose(); prevent base Static.update() from conflicting.

    def _watch_collapsed(self, collapsed: bool) -> None:
        try:
            self.query_one(".title-left", Static).update(self._left)
        except NoMatches:
            pass

    def update_sections(
        self,
        left_collapsed: str | None = None,
        left_expanded: str | None = None,
        center: str | None = None,
        right: str | None = None,
    ):
        if left_collapsed is not None:
            self._left_collapsed = left_collapsed
        if left_expanded is not None:
            self._left_expanded = left_expanded
        if left_collapsed is not None or left_expanded is not None:
            try:
                self.query_one(".title-left", Static).update(self._left)
            except NoMatches:
                pass
        if center is not None and isinstance(self._center, str):
            self._center = center
            try:
                self.query_one(".title-center", Static).update(center)
            except NoMatches:
                pass
        if right is not None and isinstance(self._right, str):
            self._right = right
            try:
                self.query_one(".title-right", Static).update(right)
            except NoMatches:
                pass


class CustomCollapsible(Collapsible):
    """Collapsible with custom three-section title bar.

    Provides a reusable base for any widget that needs collapsible functionality
    with left/center/right sections that can be independently updated.
    """

    def __init__(
        self,
        left_collapsed: str | None = None,
        left_expanded: str | None = None,
        center: Widget | str = "",
        right: Widget | str = "",
        collapsed_symbol: str = "▶",
        expanded_symbol: str = "▼",
        start_collapsed: bool = True,
        **kwargs,
    ):
        super().__init__(title="", collapsed=start_collapsed, **kwargs)
        self._title: DividedCollapsibleTitleBar = DividedCollapsibleTitleBar(
            left_collapsed=left_collapsed,
            left_expanded=left_expanded,
            center=center,
            right=right,
            collapsed_symbol=collapsed_symbol,
            expanded_symbol=expanded_symbol,
            start_collapsed=start_collapsed,
        )

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        return f"""
            CustomCollapsible {{
                background: {theme.background};
                border: none;
                margin: 0;
                padding: 0;
            }}

            CustomCollapsible > Contents {{
                padding: 0 1 0 1;
                border-top: {theme.box};
            }}

            {DividedCollapsibleTitleBar.get_css(theme)}
            """

    def update_title(
        self,
        left_collapsed: str | None = None,
        left_expanded: str | None = None,
        center: str | None = None,
        right: str | None = None,
    ):
        self._title.update_sections(
            left_collapsed=left_collapsed,
            left_expanded=left_expanded,
            center=center,
            right=right,
        )


class CollapsibleTextBox(Widget, MutableTextBox):
    """A collapsible text block widget for reasoning, verbose output, etc.

    Similar to StatsBar pattern - a Widget that contains a Collapsible.
    Provides click-to-toggle functionality for long text content.
    """

    def __init__(
        self,
        content: str | Syntax,
        title: str | None = None,
        collapsed: bool = False,
        italic: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._content = content
        self._content_classes = "box-content " + ("italic" if italic else "")
        self._collapsed = collapsed
        self.border_title = title

    def compose(self):
        self._collapsible = CustomCollapsible(
            right=CopyButton(
                lambda: self._content
                if isinstance(self._content, str)
                else self._content.code
            ),
            start_collapsed=self._collapsed,
        )
        self._text_container = Static(
            self._content, markup=False, classes=self._content_classes
        )
        with self._collapsible:
            yield self._text_container

    def append(self, line: str) -> None:
        """Append a line to the content and scroll the conversation to the end."""
        self._content = str(self._text_container.renderable) + line
        self._text_container.update(self._content)
        self._on_content_changed()

    def reset(self, content: str) -> None:
        self._content = content
        self._text_container.update(content)
        self._on_content_changed()

    def _on_content_changed(self):
        self.refresh(layout=True)
        parent = self.parent
        while parent is not None:
            if hasattr(parent, "scroll_end") and hasattr(parent, "call_after_refresh"):
                parent.scroll_end(animate=False)
                parent.call_after_refresh(parent.scroll_end)
                break
            parent = parent.parent

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        """Generate CSS for CollapsibleTextBox."""
        return f"""
        CollapsibleTextBox {{
            margin: 1 0 1 1;
            height: auto;
            padding: 0 0;
            border: solid {theme.box};
            border-title-style: bold;
            color: {theme.text};
            background: {theme.background};
        }}

        .italic {{
            text-style: italic;
        }}

        {CustomCollapsible.get_css(theme)}
        {CopyButton.get_css(theme)}
        """
