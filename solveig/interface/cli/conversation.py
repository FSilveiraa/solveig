"""Conversation area widget for displaying messages and content."""

from rich.syntax import Syntax
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Static

from solveig.interface.themes import Palette
from solveig.utils.file import Metadata

from .tree_display import TreeDisplay
from .widgets import SectionHeader, TextBox

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
        self._group_stack = []  # Stack of current group containers

    async def add_text(self, text: str, style: str = "text", markup: bool = False):
        """Add text with specific styling using semantic style names."""
        style_class = f"{style}_message" if style != "text" else style
        text_widget = Static(text, classes=style_class, markup=markup)

        # Add to current group or main area
        target = self._group_stack[-1] if self._group_stack else self
        await target.mount(text_widget)
        self.scroll_end()

    async def add_text_block(self, content: str | Syntax, title: str | None = None):
        """Add a text block with border and optional title."""
        text_block = TextBox(content, title=title)

        # Add to current group or main area
        target = self._group_stack[-1] if self._group_stack else self
        await target.mount(text_block)
        self.scroll_end()

    async def add_section_header(self, title: str, width: int = 80):
        """Add a section header."""
        section_header = SectionHeader(title, width)

        # Add to current group or main area
        target = self._group_stack[-1] if self._group_stack else self
        await target.mount(section_header)
        self.scroll_end()

    async def add_tree_display(
        self,
        metadata: Metadata,
        title: str | None = None,
        display_metadata: bool = False,
    ):
        """Add an interactive tree display widget."""
        tree_widget = TreeDisplay(metadata, display_metadata)
        if title:
            tree_widget.border_title = title

        # Add to current group or main area
        target = self._group_stack[-1] if self._group_stack else self
        await target.mount(tree_widget)
        self.scroll_end()

    async def enter_group(self, title: str):
        """Enter a new group container."""
        target = self._group_stack[-1] if self._group_stack else self

        # Print title before adding group
        title_corner = Static(f"┏━ [bold]{title}[/]", classes="group_top")
        await target.mount(title_corner)

        # Create group container with border styling for content and mount it
        group_container = Vertical(classes="group_container")
        await target.mount(group_container)

        # Push onto stack
        self._group_stack.append(group_container)
        self.scroll_end()

    async def exit_group(self):
        """Exit the current group container."""
        if self._group_stack:
            self._group_stack.pop()
            self.scroll_end()

            # Print end cap after exiting group
            end_corner = Static("┗━━━", classes="group_bottom")
            target = self._group_stack[-1] if self._group_stack else self
            await target.mount(end_corner)

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        """Generate CSS for conversation area and related widgets."""
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
        }}

        TextBox {{
            border: solid {theme.box};
            margin: 1;
            padding: 0 1;
        }}

        SectionHeader {{
            color: {theme.section};
            text-style: bold;
            margin: 1 0;
            padding: 0 0;
        }}

        .group_container {{
            border-left: heavy {theme.group};
            padding-left: 1;
            margin: 0 0 0 1;
            height: auto;
            min-height: 0;
        }}

        .group_bottom {{
            color: {theme.group};
            margin: 0 0 1 1;
        }}

        .group_top {{
            color: {theme.group};
            margin: 1 0 0 1;
        }}

        {TreeDisplay.get_css(theme)}
        """
