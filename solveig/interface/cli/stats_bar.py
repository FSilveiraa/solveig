"""Stats bar - collapsible widget containing stats tables."""

import time

from textual.containers import Horizontal
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import DataTable, Static
from textual.widgets._data_table import RowKey

from solveig.interface.cli.collapsible_widgets import CustomCollapsible
from solveig.interface.themes import Palette
from solveig.utils.file import Filesystem


class StatsBar(Widget):
    """Stats bar with collapsible table content."""

    def __init__(self, theme: Palette, **kwargs):
        super().__init__(**kwargs)
        self._timer: Timer | None = None
        self._spinner = None
        self._status = "Initializing"
        self._tokens = (0, 0)
        self._model = ""
        self._url = ""
        self._path = Filesystem.get_current_directory(simplify=True)
        self._row_keys: dict[str, RowKey] = {}
        self._theme = theme

    @property
    def tokens(self):
        return f"{self._tokens[0]}↑ / {self._tokens[1]}↓"

    def compose(self):
        """Create collapsible with stats tables."""
        # Create our custom collapsible with responsive title
        collapsed_text = "Click for more stats"
        expanded_text = "Click to collapse"

        self._collapsible = CustomCollapsible(
            collapsed_text=collapsed_text,
            expanded_text=expanded_text,
            status=self._status,
            path=self._path,
            theme=self._theme,
            start_collapsed=True,
        )

        with self._collapsible:
            # Create detail tables - shown when expanded with flexible sizing
            self._table1 = DataTable(
                show_header=False, zebra_stripes=False, classes="stats-table"
            )
            self._col1 = self._table1.add_column("stats1", width=None)  # Auto-sizing
            self._row_keys["table1_row1"] = self._table1.add_row(
                f"Tokens: {self.tokens}"
            )

            self._table2 = DataTable(
                show_header=False, zebra_stripes=False, classes="stats-table"
            )
            self._col2 = self._table2.add_column("stats2", width=None)  # Auto-sizing
            self._row_keys["table2_row1"] = self._table2.add_row(
                f"Endpoint: {self._url}"
            )

            self._table3 = DataTable(
                show_header=False, zebra_stripes=False, classes="stats-table"
            )
            self._col3 = self._table3.add_column("stats3", width=None)  # Auto-sizing
            self._row_keys["table3_row1"] = self._table3.add_row(
                f"Model: {self._model}"
            )

            yield Horizontal(
                self._table1,
                Static("│", classes="stats-separator"),
                self._table2,
                Static("│", classes="stats-separator"),
                self._table3,
                classes="stats-container",
            )

    def on_mount(self):
        """Update both title and tables for initial setup."""
        self._refresh_title()
        self._refresh_stats()

    def update(
        self,
        status=None,
        tokens: tuple[int, int] | None = None,
        model=None,
        url=None,
        path=None,
    ):
        """Update the stats dashboard with new information."""
        updated_title = updated_stats = False

        if status is not None:
            self._status = status
            updated_title = True

        if path is not None:
            # path should be a canonical Path passed by command.py or any other cwd-altering operation, then formatted for ~
            # if everything is implemented correctly, then passing the path below should be the same as not passing
            abs_path = Filesystem.get_absolute_path(path)
            self._path = Filesystem.get_current_directory(abs_path, simplify=True)
            updated_title = True

        if tokens is not None:
            self._tokens = tokens
            updated_stats = True

        if model is not None:
            self._model = model
            updated_stats = True

        if url is not None:
            self._url = url
            updated_stats = True

        if updated_title:
            self._refresh_title()
        if updated_stats:
            self._refresh_stats()

    def set_spinner(self, spinner):
        """Set spinner for status animation."""
        self._spinner = spinner
        self._refresh_title()

    def clear_spinner(self):
        """Clear spinner from status display."""
        self._spinner = None
        self._refresh_title()

    def _refresh_title(self):
        """Update only the collapsible title (lightweight, for frequent spinner updates)."""
        status_text = self._status
        if self._spinner:
            frame = self._spinner.render(time.time())
            spinner_char = frame.plain if hasattr(frame, "plain") else str(frame)
            status_text = f"{spinner_char} {status_text}"

        self._collapsible.update_title_content(status_text, self._path)

    def _refresh_stats(self):
        """Update table content (heavy, only when stats actually change)."""
        if not self._row_keys:
            return

        # Clear and re-add rows to force column width recalculation
        self._table1.clear()
        self._table2.clear()
        self._table3.clear()

        self._row_keys["table1_row1"] = self._table1.add_row(f"Tokens: {self.tokens}")
        self._row_keys["table2_row1"] = self._table2.add_row(f"Endpoint: {self._url}")
        self._row_keys["table3_row1"] = self._table3.add_row(f"Model: {self._model}")

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

        /* Stats container responsive layout */
        .stats-container {{
            width: 100%;
            height: auto;
        }}

        .stats-table {{
            overflow: hidden;
            background: {theme.background};
            color: {theme.text};
        }}

        .stats-table > .datatable--cursor {{
            background: {theme.background};
            color: {theme.text};
        }}

        .stats-table > .datatable--hover {{
            background: {theme.background};
            color: {theme.text};
        }}

        .stats-separator {{
            width: 1;
            margin: 0 1 0 1;
            height: 100%;
            border: none;
            color: {theme.box};
            text-align: center;
        }}
        """
