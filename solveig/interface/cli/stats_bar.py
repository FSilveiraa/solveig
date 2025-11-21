"""Stats bar - collapsible widget containing stats tables."""

import time

from textual.widgets import DataTable, Static, Collapsible
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets._collapsible import CollapsibleTitle

from solveig.interface.themes import Palette
from solveig.utils.file import Filesystem


class CustomTitleBar(CollapsibleTitle):
    """Custom title bar with responsive left/center/right layout."""

    def __init__(self, action_text: str, status_text: str, path_text: str, theme: Palette, collapsed: bool = True):
        # CollapsibleTitle requires these parameters
        self._action_text = action_text
        self._status_text = status_text
        self._path_text = path_text
        self._theme = theme
        super().__init__(
            label="",
            collapsed_symbol="▶",
            expanded_symbol="▼",
            collapsed=collapsed
        )

    def compose(self):
        """Override to yield three Static widgets instead of string content."""
        left_content, center_content, right_content = self._get_content()

        yield Horizontal(
            Static(left_content, classes="title-left"),
            Static(center_content, classes="title-center"),
            Static(right_content, classes="title-right"),
            classes="custom-title-bar"
        )

    def _watch_collapsed(self, collapsed: bool) -> None:
        """Override to update our Static widgets when collapsed state changes."""
        self._update_static_widgets()

    def _get_content(self):
        """Generate content for the three title sections."""
        symbol = self.collapsed_symbol if self.collapsed else self.expanded_symbol
        left_content = f"{symbol} {self._action_text}"
        center_content = f"[{self._theme.info}]{self._status_text}[/]"
        right_content = self._path_text
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
        except:
            # If not mounted yet, will update when it mounts
            pass

    def update_content(self, action_text=None, status_text=None, path_text=None):
        """Update the content of the title sections."""
        if action_text is not None:
            self._action_text = action_text
        if status_text is not None:
            self._status_text = status_text
        if path_text is not None:
            self._path_text = path_text

        self._update_static_widgets()


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

    def __init__(self, theme: Palette, **kwargs):
        super().__init__(**kwargs)
        self._timer = None
        self._spinner = None
        self._status = "Initializing"
        self._tokens = (0, 0)
        self._model = ""
        self._url = ""
        self._path = Filesystem.get_current_directory(simplify=True)
        self._row_keys = {}
        self._theme = theme

    @property
    def tokens(self):
        return f"{self._tokens[0]}↑ / {self._tokens[1]}↓"

    def compose(self):
        """Create collapsible with stats tables."""
        # Create our custom collapsible with responsive title
        action_text = "Click for more stats"
        status_text = self._status
        path_text = f"🗁  {self._path}"

        self._collapsible = CustomCollapsible(action_text, status_text, path_text, self._theme, collapsed=True)

        with self._collapsible:
            # Create detail tables - shown when expanded with flexible sizing
            self._table1 = DataTable(show_header=False, zebra_stripes=False, classes="stats-table")
            self._col1 = self._table1.add_column("stats1", width=None)  # Auto-sizing
            self._row_keys["table1_row1"] = self._table1.add_row(f"Tokens: {self.tokens}")

            self._table2 = DataTable(show_header=False, zebra_stripes=False, classes="stats-table")
            self._col2 = self._table2.add_column("stats2", width=None)  # Auto-sizing
            self._row_keys["table2_row1"] = self._table2.add_row(f"Endpoint: {self._url}")

            self._table3 = DataTable(show_header=False, zebra_stripes=False, classes="stats-table")
            self._col3 = self._table3.add_column("stats3", width=None)  # Auto-sizing
            self._row_keys["table3_row1"] = self._table3.add_row(f"Model: {self._model}")

            yield Horizontal(
                self._table1,
                Static("│", classes="separator"),
                self._table2,
                Static("│", classes="separator"),
                self._table3,
                classes="stats-container"
            )

    def on_mount(self):
        """Update displays after mounting."""
        self._update_all_displays()

    def update(self, status=None, tokens: tuple[str, str] | None = None, model=None, url=None, path=None):
        """Update the stats dashboard with new information."""
        updated = False

        if status is not None:
            self._status = status
            updated = True

        if tokens is not None:
            self._tokens = tokens
            updated = True

        if model is not None:
            self._model = model
            updated = True

        if url is not None:
            self._url = url
            updated = True

        if path is not None:
            # path should be a canonical Path passed by command.py or any other cwd-altering operation, then formatted for ~
            # if everything is implemented correctly, then passing the path below should be the same as not passing
            abs_path = Filesystem.get_absolute_path(path)
            self._path = Filesystem.get_current_directory(abs_path, simplify=True)
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
        self._table1.update_cell(self._row_keys["table1_row1"], self._col1, f"Tokens: {self.tokens}")
        self._table2.update_cell(self._row_keys["table2_row1"], self._col2, f"Endpoint: {self._url}")
        self._table3.update_cell(self._row_keys["table3_row1"], self._col3, f"Model: {self._model}")

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

        /* Custom title bar responsive layout */
        .custom-title-bar {{
            width: 100%;
            height: 1;
        }}

        .title-left {{
            text-align: left;
            width: 1fr;
        }}

        .title-center {{
            text-align: center;
            width: auto;
        }}

        .title-right {{
            text-align: right;
            width: 1fr;
        }}

        /* Stats container responsive layout */
        .stats-container {{
            width: 100%;
            height: auto;
        }}

        .stats-table {{
            width: 1fr;
            min-width: 0;
            overflow: hidden;
            scrollbar-size: 0 0;
        }}

        .separator {{
            width: 1;
            height: 100%;
            border: none;
            color: {theme.box};
            text-align: center;
        }}
        """