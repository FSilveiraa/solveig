"""Stats bar - collapsible widget containing stats tables."""

import time

from textual.widgets import DataTable, Static, Collapsible
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets._collapsible import CollapsibleTitle

from solveig.interface.themes import Palette


class CustomTitleBar(CollapsibleTitle):
    """Custom title bar with responsive left/center/right layout."""

    def __init__(self, action_text: str, status_text: str, path_text: str, theme: Palette, collapsed: bool = True, **kwargs):
        # CollapsibleTitle requires these parameters
        self._action_text = action_text
        self._status_text = status_text
        self._path_text = path_text
        self._theme = theme
        super().__init__(
            label="",
            collapsed_symbol="▶",
            expanded_symbol="▼",
            collapsed=collapsed,
            **kwargs
        )

    def _update_label(self):
        """Override to provide our custom layout instead of the default label display."""
        left_content = f"{self.collapsed_symbol} {self._action_text}"
        center_content = f"[{self._theme.info}]{self._status_text}[/]"
        right_content = self._path_text

        # Simple spacing for now - CSS will handle responsive layout
        full_content = f"{left_content}     {center_content}     {right_content}"
        self.update(full_content)

    def update_content(self, action_text=None, status_text=None, path_text=None):
        """Update the content of the title sections."""
        if action_text is not None:
            self._action_text = action_text
        if status_text is not None:
            self._status_text = status_text
        if path_text is not None:
            self._path_text = path_text
        self._update_label()


class CustomCollapsible(Collapsible):
    """Collapsible with custom responsive title bar."""

    def __init__(self, action_text: str, status_text: str, path_text: str, theme: Palette, collapsed: bool = True, **kwargs):
        super().__init__(title="", collapsed=collapsed, **kwargs)
        # Replace the _title widget with our custom one
        self._title = CustomTitleBar(action_text, status_text, path_text, theme, collapsed=collapsed)

    def update_title_content(self, action_text=None, status_text=None, path_text=None):
        """Update the title bar content."""
        self._title.update_content(action_text, status_text, path_text)


class StatsBar(Widget):
    """Stats bar with collapsible table content."""

    def __init__(self, width: int, theme: Palette, **kwargs):
        super().__init__(**kwargs)
        self._timer = None
        self._spinner = None
        self._status = "Initializing"
        self._tokens = (0, 0)
        self._model = ""
        self._url = ""
        self._path = "/home/francisco/Documents/Fun/solveig"
        self._row_keys = {}
        self._screen_width = width - 6
        self._theme = theme

    def compose(self):
        """Create collapsible with stats tables."""
        column_width = self._screen_width // 3

        # Create our custom collapsible with responsive title
        action_text = "Click for more stats"
        status_text = self._status
        path_text = f"🗁  {self._path}"

        self._collapsible = CustomCollapsible(action_text, status_text, path_text, self._theme, collapsed=True)

        with self._collapsible:
            # Create detail tables - shown when expanded
            self._table1 = DataTable(show_header=False, zebra_stripes=False)
            self._col1 = self._table1.add_column("stats1", width=column_width)
            self._row_keys["table1_row2"] = self._table1.add_row(f"Path: {self._path}")

            self._table2 = DataTable(show_header=False, zebra_stripes=False)
            self._col2 = self._table2.add_column("stats2", width=column_width)
            self._row_keys["table2_row2"] = self._table2.add_row(f"Endpoint: {self._url}")

            self._table3 = DataTable(show_header=False, zebra_stripes=False)
            self._col3 = self._table3.add_column("stats3", width=column_width)
            self._row_keys["table3_row2"] = self._table3.add_row(f"Model: {self._model}")

            yield Horizontal(
                self._table1,
                Static("│", classes="separator"),
                self._table2,
                Static("│", classes="separator"),
                self._table3
            )

    def on_mount(self):
        """Update displays after mounting."""
        self._update_all_displays()

    def update_status_info(self, status=None, tokens=None, model=None, url=None, path=None, **kwargs):
        """Update the stats dashboard with new information."""
        updated = False

        if status is not None:
            self._status = status
            updated = True

        if tokens is not None:
            if isinstance(tokens, tuple):
                self._tokens = tokens
            elif isinstance(tokens, str):
                self._tokens = tokens
            else:
                self._tokens = (tokens, 0)
            updated = True

        if model is not None:
            self._model = model
            updated = True

        if url is not None:
            self._url = url
            updated = True

        if path is not None:
            self._path = str(path)
            updated = True

        if updated:
            self._update_all_displays()

    def set_spinner(self, spinner):
        """Set spinner for status animation."""
        self._spinner = spinner
        self._update_all_displays()

    def clear_spinner(self):
        """Clear spinner from status display."""
        self._spinner = None
        self._update_all_displays()

    def _update_all_displays(self):
        """Update collapsible title and detail table cells with current values."""
        if not self._row_keys:
            return

        # Update custom collapsible title
        action_text = "Click for more stats"
        status_text = self._status
        if self._spinner:
            frame = self._spinner.render(time.time())
            spinner_char = frame.plain if hasattr(frame, "plain") else str(frame)
            status_text = f"{spinner_char} {status_text}"

        path_text = f"🗁  {self._path}"
        self._collapsible.update_title_content(action_text, status_text, path_text)

        # Update detail table cells (shown when expanded)
        self._table1.update_cell(self._row_keys["table1_row2"], self._col1, f"Path: {self._path}")
        self._table2.update_cell(self._row_keys["table2_row2"], self._col2, f"Endpoint: {self._url}")
        self._table3.update_cell(self._row_keys["table3_row2"], self._col3, f"Model: {self._model}")

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        """Generate CSS for stats bar."""
        return f"""
        StatsBar {{
            dock: bottom;
            height: auto;
            max-height: 8;
            background: {theme.background};
            color: {theme.text};
            border: solid {theme.box};
        }}

        StatsBar Collapsible {{
            background: {theme.background};
            border: none;
            margin: 0;
            padding: 0;
        }}

        StatsBar CollapsibleTitle {{
            color: {theme.text};
            background: {theme.background};
        }}

        .separator {{
            width: 1;
            height: 100%;
            border: none;
            color: {theme.box};
            text-align: center;
        }}
        """