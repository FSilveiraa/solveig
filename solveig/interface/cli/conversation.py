"""Conversation area widget for displaying messages and content."""

from rich.syntax import Syntax
from textual.containers import ScrollableContainer
from textual.widgets import Collapsible, Markdown, Static

from solveig.interface.themes import Palette
from solveig.utils.file import Metadata

from .collapsible_widgets import (
    CollapsibleTextBox,
    CustomCollapsible,
)
from .tree_display import TreeDisplay
from .widgets import Comment, SectionHeader

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
        self._group_stack: list[CustomCollapsible] = []

    @property
    def _mount_target(self):
        """The widget to mount new elements into: innermost group's Contents, or self."""
        return (
            self._group_stack[-1].query_one(Collapsible.Contents)
            if self._group_stack
            else self
        )

    async def _add_element(self, element):
        """Add element to the scrollable container."""
        await self._mount_target.mount(element)

        # Defer layout refresh so child widgets finish composing first, then
        # force a layout pass with their correct sizes (fixes height: auto on
        # complex widgets like Tree, Collapsible, etc.)
        def _after_mount():
            element.refresh(layout=True)
            self.scroll_end()
            self.call_after_refresh(self.scroll_end)

        self.call_after_refresh(_after_mount)

    async def add_text(self, text: str, style: str = "text", markup: bool = False):
        """Add text with specific styling using semantic style names."""
        style_class = f"{style}_message" if style != "text" else style
        await self._add_element(Static(text, classes=style_class, markup=markup))

    async def add_text_box(
        self,
        content: str | Syntax | Markdown,
        title: str | None = None,
        collapsed: bool = False,
        italic: bool = False,
    ):
        """Add a collapsible text block (for reasoning, verbose output, etc.)."""
        box = CollapsibleTextBox(
            content, title=title, italic=italic, collapsed=collapsed
        )
        await self._add_element(box)
        return box

    async def add_section_header(self, title: str):
        """Add a section header."""
        await self._add_element(SectionHeader(title))

    async def add_tree_display(
        self,
        metadata: Metadata,
        title: str | None = None,
        display_metadata: bool = False,
        expand_root=True,
    ):
        """Add an interactive tree display widget."""
        tree_widget = TreeDisplay(
            metadata=metadata,
            display_metadata=display_metadata,
            expand_root=expand_root,
        )
        if title:
            tree_widget.border_title = title
        await self._add_element(tree_widget)

    async def enter_group(self, title: str) -> CustomCollapsible:
        """Enter a new collapsible group. Returns the group widget."""
        group = CustomCollapsible(
            left_collapsed=title,
            left_expanded=title,
            collapsed_symbol="▶",
            expanded_symbol="▼",
            start_collapsed=False,
            classes="tool_group",
        )
        await self._mount_target.mount(group)
        self._group_stack.append(group)
        self.scroll_end()
        self.call_after_refresh(self.scroll_end)
        return group

    async def exit_group(self, auto_collapse: bool = False) -> None:
        """Exit the current group, optionally collapsing it."""
        if self._group_stack:
            group = self._group_stack.pop()
            await group.mount(Static("┗━━━", classes="tool_group_end"))
            if auto_collapse:
                group.collapsed = True
            self.scroll_end()
            self.call_after_refresh(self.scroll_end)

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        """Generate CSS for conversation area and group-related widgets."""
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
            padding: 0 0 1 1;
        }}

        .tool_group {{
            height: auto;
            margin: 1 0 0 0;
        }}

        .tool_group > Contents {{
            border: none;
            border-left: heavy {theme.group};
            padding: 0 0 0 1;
            height: auto;
        }}

        .tool_group_end {{
            color: {theme.group};
        }}

        .tool_group.-collapsed > .tool_group_end {{
            display: none;
        }}

        .tool_group DividedCollapsibleTitleBar {{
            color: {theme.group};
            text-style: bold;
            padding: 0;
        }}

        .tool_group DividedCollapsibleTitleBar .title-left:hover {{
            color: {theme.section};
        }}

        {Comment.get_css(theme)}
        {CustomCollapsible.get_css(theme)}
        {CollapsibleTextBox.get_css(theme)}
        {SectionHeader.get_css(theme)}
        {TreeDisplay.get_css(theme)}
        """

        # {TextBox.get_css(theme)}
