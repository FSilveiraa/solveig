"""Conversation area widget for displaying messages and content."""

from rich.syntax import Syntax
from textual import events
from textual.containers import ScrollableContainer
from textual.dom import DOMNode
from textual.widget import Widget
from textual.widgets import Collapsible, Markdown, Static

from .buttons import MessageButton
from .collapsible_widgets import (
    CollapsibleTextBox,
    CustomCollapsible,
)
from .tree_display import TreeDisplay
from .widgets import Comment

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
        await self.remove_children()

    async def add_element(self, container: Widget, *elements: Widget) -> None:
        """Mount widgets into the given container.

        `container` is either the area itself (transcript/root rendering) or a
        group's contents (scoped tool output inside `with_group`). Uses
        Textual's native `mount(*widgets)` multi-mount, then a single deferred
        layout pass once children finish composing (fixes height: auto on
        complex widgets like Tree, Collapsible).
        """
        await container.mount(*elements)

        # Defer layout refresh so child widgets finish composing first, then
        # force a layout pass with their correct sizes (fixes height: auto on
        # complex widgets like Tree, Collapsible, etc.)
        def _after_mount():
            for element in elements:
                element.refresh(layout=True)
            self.scroll_end()
            self.call_after_refresh(self.scroll_end)

        self.call_after_refresh(_after_mount)

    async def add_text(
        self, text: str, style: str = "text", markup: bool = False, *, container
    ):
        """Add text with specific styling using semantic style names."""
        style_class = f"{style}_message" if style != "text" else style
        await self.add_element(
            container, Static(text, classes=style_class, markup=markup)
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
        await self.add_element(container, box)
        return box

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
    def get_css(cls) -> str:
        """CSS for the conversation area and group-related widgets. `$user-turn-bg`
        (the tinted user background) is a theme variable computed per palette."""
        return (
            """
        ConversationArea {
            height: 1fr;
            scrollbar-gutter: stable;
            scrollbar-size: 1 1;
            scrollbar-color: $box;
            scrollbar-color-hover: $section;
            scrollbar-color-active: $section;
            scrollbar-background: $background;
            scrollbar-background-hover: $background;
            scrollbar-background-active: $background;
            /* Trailing space is the last child's own bottom margin (1); padding
               here would add to it (padding never collapses) and give 2. */
            padding: 0;
        }

        /* The user-turn tint lives on the comment TEXT only, not the action
           buttons under it - so tint the Markdown child, not the whole
           EditableComment. Horizontal inset comes from .text_comment's margin;
           this padding is just breathing room for the text inside the tint. */
        .role-user > Markdown {
            background: $user-turn-bg;
            padding: 0 1;
        }

        .group {
            height: auto;
            /* 1 on all four sides, collapsing (max) with siblings. */
            margin: 1;
            padding-bottom: 0;
        }

        .group > Contents {
            border: none;
            border-left: heavy $group;
            padding: 0 0 0 1;
            height: auto;
        }

        .group_end {
            color: $group;
        }

        .group_pending {
            color: $group-pending;
        }

        .group > DividedCollapsibleTitleBar {
            color: $group;
            text-style: bold;
            padding: 0;
        }

        .group.-hovering > DividedCollapsibleTitleBar {
            color: $section;
        }

        .group.-hovering > Contents {
            border-left: heavy $section;
        }

        .group.-hovering > .group_end {
            color: $section;
        }

        .group.-hovering > .group_pending {
            color: $section;
        }
        """
            + Comment.get_css()
            + MessageButton.get_css()
            + CustomCollapsible.get_css()
            + CollapsibleTextBox.get_css()
            + TreeDisplay.get_css()
        )
