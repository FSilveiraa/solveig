"""Basic UI widgets for the Textual CLI interface."""

from rich.syntax import Syntax
from textual.widgets import Static


class TextBox(Static):
    """A text block widget with optional title and border."""

    def __init__(self, content: str | Syntax, title: str | None = None, **kwargs):
        super().__init__(content, markup=False, **kwargs)
        self.border = "solid"
        if title:
            self.border_title = title
        self.add_class("text_block")


class SectionHeader(Static):
    """A section header widget with line extending to the right."""

    def __init__(self, title: str, width: int = 80):
        # Calculate the line with dashes
        # Create the section line
        header_prefix = f"━━━━ {title}"
        remaining_width = width - len(header_prefix) - 3
        dashes = "━" * max(0, remaining_width)

        section_line = f"{header_prefix} {dashes}"
        super().__init__(section_line)
        self.add_class("section_header")
