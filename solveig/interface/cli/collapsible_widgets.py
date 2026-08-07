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

from solveig.interface.base.widgets import DiffBox, TextBox

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


class TextBoxWidget(Widget):
    """The Textual widget that draws a collapsible text block.

    NOTE: deliberately NOT the `TextBox` protocol implementer. This class is a
    widget - it composes, it is queried by type for the live code-theme restyle,
    it carries the CSS - and a widget handed across the protocol would give app
    code `.mount()`, `.remove()`, `.parent` and the rest of Textual under a name
    that promises three methods. `CollapsibleTextBox` owns one of these and is
    what crosses the boundary.

    Frontend code inside `interface/cli/` talks to this directly (see
    `message_display`, which mounts one for a reasoning part) - that is not a
    boundary crossing and needs no handle.
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
    # and we don't need `isintance()` checks in update_content

    def update_content(self, renderable: str | Syntax) -> None:
        """Set the rendered content and settle the layout."""
        if isinstance(renderable, str):
            # Both Static and Markdown take a str, so no narrowing is needed.
            self._text_container.update(renderable)
        else:
            # A Rich renderable only reaches a Static: `compose` builds a
            # Markdown container solely for content that arrived as Markdown,
            # and nothing re-renders that as Syntax.
            assert isinstance(self._text_container, Static)
            self._text_container.update(renderable)
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
        """Generate CSS for TextBoxWidget."""
        return (
            """
        TextBoxWidget {
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


class CollapsibleTextBox(TextBox):
    """The `TextBox` handed to a caller after the interface mounts a text block.

    NOTE: inherits the protocol EXPLICITLY, which the old widget-based version
    could not - `_MessagePumpMeta` and a Protocol's metaclass are unrelated, so
    while this class WAS a widget the conformance check could only happen at
    `interface.py`'s return annotation. Owning a widget instead of being one
    moves the check to this class definition, which is the hole
    `TreeBox.refresh` drifted through.

    Delegation is one hop: this is not a wrapper around a bigger object with the
    same job, it is the API half of a class that used to have two jobs.
    """

    def __init__(
        self,
        content: str | Syntax | Markdown,
        title: str | None = None,
        collapsed: bool = False,
        italic: bool = False,
    ) -> None:
        self.widget = TextBoxWidget(
            content, title=title, collapsed=collapsed, italic=italic
        )

    def append(self, text: str) -> None:
        self.widget.update_content(f"{self.widget.content}\n{text.rstrip('\n')}")

    def clear(self) -> None:
        self.widget.update_content("")

    def replace(self, text: str) -> None:
        self.widget.update_content(text)


class CollapsibleDiffBox(DiffBox):
    """The `DiffBox` handed to a caller after the interface mounts a diff.

    Renders through the same widget as `CollapsibleTextBox` but is a peer, not a
    subclass: `replace()` takes two arguments because a diff has two sides, and
    inheriting the text box's one-argument `replace` meant an incompatible
    override that only a `type: ignore` held together. Two protocols disagreeing
    on a method name is a sign the classes are siblings.
    """

    def __init__(
        self,
        content: str | Syntax,
        old_content: str,
        new_content: str,
        title: str | None = None,
    ) -> None:
        self.widget = TextBoxWidget(content, title=title)
        self._old_content = old_content
        self._new_content = new_content

    def replace(self, old_content: str, new_content: str) -> None:
        """Replace both sides of the diff. Re-computes and re-renders."""
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
            self.widget.update_content(
                Syntax(diff_text, lexer="diff", theme=self._live_code_theme())
            )
        else:
            self.widget.update_content("(Same content)")

    def _live_code_theme(self) -> str:
        """Resolve the active code theme via the app's interface ref.

        ``SolveigTextualApp`` stores the interface as ``_interface_ref`` (not
        ``interface``), so a direct ``app.interface`` lookup silently fell back
        to ``"monokai"``.  Reach the real interface and let its
        ``_live_code_theme`` resolve the root, matching how the rest of the
        frontend reads the live theme.
        """
        interface = getattr(self.widget.app, "_interface_ref", None)
        if interface is not None and hasattr(interface, "_live_code_theme"):
            return interface._live_code_theme()
        return "monokai"
