"""Stats bar - collapsible widget containing stats tables."""

import time

from textual.widgets import DataTable, Static, Collapsible
from textual.containers import Horizontal
from textual.widget import Widget

from solveig.interface.themes import Palette


class StatsBar(Widget):
    """Stats bar with collapsible table content."""

    def __init__(self, width: int = 100, **kwargs):
        super().__init__(**kwargs)
        self._timer = None
        self._spinner = None
        self._status = "Initializing"
        self._tokens = (0, 0)
        self._model = ""
        self._url = ""
        self._path = "/home/francisco/Documents/Fun/solveig"
        self._row_keys = {}
        self._screen_width = width - 15

    def compose(self):
        """Create collapsible with stats tables."""
        column_width = self._screen_width // 3
        with Collapsible(title="Stats", collapsed=True):
            # Create tables with proper content
            self._table1 = DataTable(show_header=False, zebra_stripes=False)
            self._col1 = self._table1.add_column("stats1", width=column_width)
            self._row_keys["table1_row1"] = self._table1.add_row("Click to expand")
            self._row_keys["table1_row2"] = self._table1.add_row("Model:")

            self._table2 = DataTable(show_header=False, zebra_stripes=False)
            self._col2 = self._table2.add_column("stats2", width=column_width)
            self._row_keys["table2_row1"] = self._table2.add_row("Processing")
            self._row_keys["table2_row2"] = self._table2.add_row("Endpoint:")

            self._table3 = DataTable(show_header=False, zebra_stripes=False)
            self._col3 = self._table3.add_column("stats3", width=column_width)
            self._row_keys["table3_row1"] = self._table3.add_row("Tokens:")
            self._row_keys["table3_row2"] = self._table3.add_row("Path:")

            yield Horizontal(
                self._table1,
                Static("│\n│", classes="separator"),
                self._table2,
                Static("│\n│", classes="separator"),
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
        self._update_status_display()

    def clear_spinner(self):
        """Clear spinner from status display."""
        self._spinner = None
        self._update_status_display()

    def _update_all_displays(self):
        """Update all DataTable cells with current values."""
        if not self._row_keys or not hasattr(self, '_table1'):
            return

        # Table 1 updates: Expand/Model
        self._table1.update_cell(self._row_keys["table1_row1"], self._col1, "Click to expand")
        self._table1.update_cell(self._row_keys["table1_row2"], self._col1, f"Model:  {self._model}")

        # Table 2 updates: Status/Endpoint
        status_display = self._status
        if self._spinner:
            frame = self._spinner.render(time.time())
            spinner_char = frame.plain if hasattr(frame, "plain") else str(frame)
            status_display = f"{spinner_char} {status_display}"

        self._table2.update_cell(self._row_keys["table2_row1"], self._col2, status_display)
        self._table2.update_cell(self._row_keys["table2_row2"], self._col2, f"Endpoint:  {self._url}")

        # Table 3 updates: Tokens/Path
        if isinstance(self._tokens, tuple):
            tokens_display = f"{self._tokens[0]}↑ / {self._tokens[1]}↓"
        else:
            tokens_display = str(self._tokens)

        self._table3.update_cell(self._row_keys["table3_row1"], self._col3, f"Tokens:  {tokens_display}")
        self._table3.update_cell(self._row_keys["table3_row2"], self._col3, f"Path:    {self._path}")

    def _update_status_display(self):
        """Update the status display with optional spinner."""
        self._update_all_displays()

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

        .separator {{
            width: 1;
            height: 100%;
            border: none;
            color: {theme.box};
            text-align: center;
        }}
        """