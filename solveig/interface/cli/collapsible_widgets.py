"""Reusable collapsible widget components for Textual UI.

This module provides base collapsible widgets that can be used throughout the application
for any content that needs to be expandable/collapsible (stats, reasoning, logs, etc.).
"""

import difflib

from rich.syntax import Syntax
from textual.containers import Horizontal, ScrollableContainer
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Collapsible, Markdown, Static

# HACK: CollapsibleTitle has no public export in Textual 6.1 - import from the
# private module (tracked in CLAUDE.md "Known Justified Type Hacks").
from textual.widgets._collapsible import CollapsibleTitle

from solveig.interface.base import DiffBox, TextBox

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
    def get_css(cls) -> str:
        return """
        /* Custom title bar responsive layout */
        DividedCollapsibleTitleBar {
            width: 100%;
            height: 1;
            color: $foreground;
            background: $background;
        }

        .title-left {
            text-align: left;
            width: 1fr;
        }

        .title-left:hover {
            color: $section;
        }

        .title-center {
            text-align: center;
            width: auto;
        }

        .title-right {
            text-align: right;
            width: 1fr;
        }
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
    def get_css(cls) -> str:
        return """
            CustomCollapsible {
                background: $background;
                border: none;
                margin: 0;
                padding: 0;
            }

            CustomCollapsible > Contents {
                padding: 0 1 0 1;
                border-top: solid $box;
            }
            """ + DividedCollapsibleTitleBar.get_css()

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


class CollapsibleTextBox(Widget, TextBox):
    """A collapsible text block widget for reasoning, verbose output, etc.

    Similar to StatsBar pattern - a Widget that contains a Collapsible.
    Provides click-to-toggle functionality for long text content.
    """

    def __init__(
        self,
        content: str | Syntax | Markdown,
        title: str | None = None,
        collapsed: bool = False,
        italic: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._initial_content = content
        if isinstance(self._initial_content, str):
            self._initial_content = self._initial_content.rstrip("\n")
        self._content_classes = "box-content " + ("italic" if italic else "")
        self._collapsed = collapsed
        self.border_title = title
        self._text_container: Static | Markdown

    @property
    def content(self) -> str:
        if isinstance(self._text_container, Markdown):
            return self._text_container._markdown
        elif isinstance(self._text_container, Static):
            return str(self._text_container.content)
        else:
            return str(self._text_container)

    def compose(self):
        if isinstance(self._initial_content, Markdown):
            self._text_container = self._initial_content
        else:
            self._text_container = Static(
                self._initial_content, markup=False, classes=self._content_classes
            )

        self._collapsible = CustomCollapsible(
            right=CopyButton(lambda: self.content),
            start_collapsed=self._collapsed,
        )

        with self._collapsible:
            yield self._text_container

    # Note: by coincidence, both Markdown and Static have an update(str) method, so the interface doesn't break
    # and we don't need `isintance()` checks in append/clear

    def append(self, line: str) -> None:
        """Append a line to the content and scroll the conversation to the end."""
        self._text_container.update(f"{self.content}\n{line.rstrip('\n')}")
        self._on_content_changed()

    def clear(self) -> None:
        """Empty the box content."""
        self._text_container.update("")
        self._on_content_changed()

    def replace(self, text: str) -> None:
        """Replace the entire content."""
        self._text_container.update(text)
        self._on_content_changed()

    def _on_content_changed(self):
        self.refresh(layout=True)
        parent = self.parent
        while parent is not None:
            if isinstance(parent, ScrollableContainer):
                parent.scroll_end(animate=False)
                parent.call_after_refresh(parent.scroll_end)
            # Stop after reaching the conversation area
            if parent.id == "conversation":
                break
            parent = parent.parent

    @classmethod
    def get_css(cls) -> str:
        """Generate CSS for CollapsibleTextBox."""
        return (
            """
        CollapsibleTextBox {
            /* Section content: 1 on all four sides. */
            margin: 1;
            height: auto;
            padding: 0 0;
            border: solid $box;
            border-title-style: bold;
            color: $foreground;
            background: $background;
        }

        .italic {
            text-style: italic;
        }
        """
            + CustomCollapsible.get_css()
            + CopyButton.get_css()
        )


class CollapsibleDiffBox(CollapsibleTextBox, DiffBox):
    """A collapsible diff display — same rendering as CollapsibleTextBox but
    carries old/new content for the DiffBox.replace() contract.

    Inherits `get_css` from CollapsibleTextBox. The `replace()` here takes
    (old_content, new_content) per DiffBox — the MRO picks this over
    TextBox's `replace(text)` because it's defined on the most-derived class.
    """

    def __init__(
        self,
        content: str | Syntax,
        old_content: str,
        new_content: str,
        title: str | None = None,
    ) -> None:
        super().__init__(content, title=title)
        self._old_content = old_content
        self._new_content = new_content

    def replace(self, old_content: str, new_content: str) -> None:  # type: ignore[override]
        """Replace both sides of the diff. Re-computes and re-renders.

        Shadows TextBox.replace(text) — DiffBox's replace takes two args
        because a diff has two sides. mypy can't reconcile the signatures
        across the MRO, hence the type: ignore.
        """
        self._old_content = old_content
        self._new_content = new_content
        old_lines = (old_content.rstrip() + "\n").splitlines(keepends=True)
        new_lines = (new_content.rstrip() + "\n").splitlines(keepends=True)
        diff_text = "".join(
            difflib.unified_diff(
                old_lines, new_lines, fromfile="original", tofile="modified"
            )
        )
        if diff_text.strip():
            assert isinstance(self._text_container, Static)
            self._text_container.update(
                Syntax(diff_text, lexer="diff", theme=self._live_code_theme())
            )
        else:
            self._text_container.update("(Same content)")
        self._on_content_changed()

    def _live_code_theme(self) -> str:
        """Resolve the active code theme via the app's interface ref.

        ``SolveigTextualApp`` stores the interface as ``_interface_ref`` (not
        ``interface``), so a direct ``self.app.interface`` lookup silently
        fell back to ``"monokai"``.  Reach the real interface and let its
        ``_live_code_theme`` resolve the root, matching how the rest of the
        frontend reads the live theme.
        """
        interface = getattr(self.app, "_interface_ref", None)
        if interface is not None and hasattr(interface, "_live_code_theme"):
            return interface._live_code_theme()
        return "monokai"
