"""Conversation area widget for displaying messages and content."""

from rich.syntax import Syntax
from textual import events
from textual.color import Color
from textual.containers import ScrollableContainer, Vertical
from textual.dom import DOMNode
from textual.widgets import Collapsible, Markdown, Static

from solveig.interface.themes import Palette
from solveig.utils.file import FileMetadata

from .buttons import MessageButton
from .collapsible_widgets import (
    CollapsibleTextBox,
    CustomCollapsible,
)
from .tree_display import TreeDisplay
from .widgets import Comment, SectionHeader

# Bottom marker for a group that hasn't resolved yet: the border-left
# appears to keep extending down, fading out row by row, until exit_group()
# swaps it for the real "┗━━━" closed cap.
GROUP_PENDING_CHAR = "┃"
GROUP_PENDING_OPACITIES = (0.5,)

BANNER = """
                              888                                  d8b
                              888                                  Y8P
                              888
  .d8888b        .d88b.       888      888  888       .d88b.       888       .d88b.
  88K           d88""88b      888      888  888      d8P  Y8b      888      d88P"88b
  "Y8888b.      888  888      888      Y88  88P      88888888      888      888  888
       X88      Y88..88P      888       Y8bd8P       Y8b.          888      Y88b 888
   88888P'       "Y88P"       888        Y88P         "Y8888       888       "Y88888
                                                                                 888
                                                                            Y8b d88P
                                                                             "Y88P"
"""


class ConversationArea(ScrollableContainer):
    """Scrollable area for displaying conversation messages."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._hovered_group: CustomCollapsible | None = None
        self._current_section_container: Vertical | None = None

    @staticmethod
    def _nearest_group(widget: DOMNode | None) -> CustomCollapsible | None:
        """Walk up from a widget to find its nearest enclosing group, if any."""
        while widget is not None and not isinstance(widget, CustomCollapsible):
            widget = widget.parent
        return widget

    def _on_mouse_move(self, event: events.MouseMove) -> None:
        group = self._nearest_group(event.widget)
        if group is not self._hovered_group:
            if self._hovered_group is not None:
                self._hovered_group.remove_class("-hovering")
            self._hovered_group = group
            if group is not None:
                group.add_class("-hovering")

    def _on_leave(self, event: events.Leave) -> None:
        if event.node is self and self._hovered_group is not None:
            self._hovered_group.remove_class("-hovering")
            self._hovered_group = None

    async def _on_click(self, event: events.Click) -> None:
        """Clicking a group's border/cap (not nested content) toggles its collapse."""
        widget = event.widget
        is_structural = isinstance(widget, Collapsible.Contents) or (
            isinstance(widget, Static)
            and (widget.has_class("group_end") or widget.has_class("group_pending"))
        )
        if is_structural:
            group = self._nearest_group(widget)
            if group is not None:
                group.collapsed = not group.collapsed

    async def clear(self) -> None:
        """Remove all mounted content, in preparation for a full redraw."""
        self._current_section_container = None
        await self.remove_children()

    async def _add_element(self, element, container) -> None:
        """Mount element into the given container."""
        await container.mount(element)

        # Defer layout refresh so child widgets finish composing first, then
        # force a layout pass with their correct sizes (fixes height: auto on
        # complex widgets like Tree, Collapsible, etc.)
        def _after_mount():
            element.refresh(layout=True)
            self.scroll_end()
            self.call_after_refresh(self.scroll_end)

        self.call_after_refresh(_after_mount)

    async def add_text(
        self, text: str, style: str = "text", markup: bool = False, *, container
    ):
        """Add text with specific styling using semantic style names."""
        style_class = f"{style}_message" if style != "text" else style
        await self._add_element(
            Static(text, classes=style_class, markup=markup), container
        )

    async def add_text_box(
        self,
        content: str | Syntax | Markdown,
        title: str | None = None,
        collapsed: bool = False,
        italic: bool = False,
        *,
        container,
    ):
        """Add a collapsible text block (for reasoning, verbose output, etc.)."""
        box = CollapsibleTextBox(
            content, title=title, italic=italic, collapsed=collapsed
        )
        await self._add_element(box, container)
        return box

    async def add_section_header(self, title: str):
        """Add a section header, then start a new tinted container for its content."""
        self._current_section_container = None
        await self._add_element(SectionHeader(title), self)
        container = Vertical(classes=f"section-{title.lower()}")
        await self._add_element(container, self)
        self._current_section_container = container

    async def add_tree_display(
        self,
        metadata: FileMetadata,
        title: str | None = None,
        display_metadata: bool = False,
        expand_root=True,
        *,
        container,
    ):
        """Add an interactive tree display widget."""
        tree_widget = TreeDisplay(
            metadata=metadata,
            display_metadata=display_metadata,
            expand_root=expand_root,
        )
        if title:
            tree_widget.border_title = title
        await self._add_element(tree_widget, container)

    async def enter_group(self, title: str, *, container) -> CustomCollapsible:
        """Mount a new collapsible group into container. Returns the group
        widget - the caller is responsible for handing it back to
        exit_group()."""
        group = CustomCollapsible(
            left_collapsed=title,
            left_expanded=title,
            collapsed_symbol="┏━ ▶",
            expanded_symbol="┏━ ▼",
            start_collapsed=False,
            classes="group",
        )
        await container.mount(group)
        for opacity in GROUP_PENDING_OPACITIES:
            marker = Static(GROUP_PENDING_CHAR, classes="group_pending")
            marker.styles.opacity = opacity
            await group.mount(marker)
        self.scroll_end()
        self.call_after_refresh(self.scroll_end)
        return group

    async def exit_group(
        self, group: CustomCollapsible, *, auto_collapse: bool = False
    ) -> None:
        """Close a group returned by enter_group(): swap its pending marker
        for the closed cap, optionally collapsing it."""
        # Only remove markers that are direct children of this group,
        # not markers from nested groups (which would also match .group_pending query).
        for pending in group.query(".group_pending"):
            # Only remove if parent is this group, not nested
            if pending.parent == group:
                await pending.remove()
        await group.mount(Static("┗━━━", classes="group_end"))
        if auto_collapse:
            group.collapsed = True
        self.scroll_end()
        self.call_after_refresh(self.scroll_end)

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        """Generate CSS for conversation area and group-related widgets."""
        background = Color.parse(theme.background)
        user_background = (
            background.darken(0.08)
            if background.brightness >= 0.5
            else background.lighten(0.08)
        )
        return f"""
        ConversationArea {{
            height: 1fr;
            scrollbar-gutter: stable;
            scrollbar-size: 1 1;
            scrollbar-color: {theme.box};
            scrollbar-color-hover: {theme.section};
            scrollbar-color-active: {theme.section};
            scrollbar-background: {theme.background};
            scrollbar-background-hover: {theme.background};
            scrollbar-background-active: {theme.background};
            /* Trailing space is the last child's own bottom margin (1); padding
               here would add to it (padding never collapses) and give 2. */
            padding: 0;
        }}

        /* Imperative-path section containers only - the live/reactive transcript
           mounts comments flat and spaces them via the role/box/group margins
           below, not here. Kept for the tint; spacing lives on the children. */
        .section-user, .section-assistant {{
            height: auto;
        }}

        .section-user {{
            background: {user_background.hex};
        }}

        /* The user-turn tint lives on the comment TEXT only, not the action
           buttons under it - so tint the Markdown child, not the whole
           EditableComment. Horizontal inset comes from .text_comment's margin;
           this padding is just breathing room for the text inside the tint. */
        .role-user > Markdown {{
            background: {user_background.hex};
            padding: 0 1;
        }}

        .group {{
            height: auto;
            /* Section content: 1 on all four sides. Collapses with siblings;
               header top-2 wins between sections. */
            margin: 1;
            padding-bottom: 0;
        }}

        .group > Contents {{
            border: none;
            border-left: heavy {theme.group};
            padding: 0 0 0 1;
            height: auto;
        }}

        .group_end {{
            color: {theme.group};
        }}

        .group_pending {{
            color: {theme.group_pending};
        }}

        .group > DividedCollapsibleTitleBar {{
            color: {theme.group};
            text-style: bold;
            padding: 0;
        }}

        .group.-hovering > DividedCollapsibleTitleBar {{
            color: {theme.section};
        }}

        .group.-hovering > Contents {{
            border-left: heavy {theme.section};
        }}

        .group.-hovering > .group_end {{
            color: {theme.section};
        }}

        .group.-hovering > .group_pending {{
            color: {theme.section};
        }}

        {Comment.get_css(theme)}
        {MessageButton.get_css(theme)}
        {CustomCollapsible.get_css(theme)}
        {CollapsibleTextBox.get_css(theme)}
        {SectionHeader.get_css(theme)}
        {TreeDisplay.get_css(theme)}
        """
