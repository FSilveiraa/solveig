"""Stats dashboard - simple text box."""

from textual.widgets import Static, DataTable
from textual.containers import Horizontal

from solveig.interface.themes import Palette


class StatsDashboard(Horizontal):
    """Simple text stats dashboard."""

    def __init__(self, width: int, **kwargs):
        super().__init__(**kwargs)
        self._timer = None
        self._spinner = None
        self._status = "Initializing"
        self._tokens = (0, 0)
        self._model = ""
        self._url = ""
        self._path = "/home/francisco/Documents/Fun/solveig"
        self._row_keys = {}
        # this looks hardcoded, but it's sort of proper formatting since it's the "extra screen width" taken up by padding, boxes, etc
        # altering this value will visually impact the display AT ANY WIDTH
        self._screen_width = width - 15

    def compose(self):
        """Create placeholder tables - will be populated in on_mount."""
        # Create empty tables first
        self._table1 = DataTable(show_header=False, zebra_stripes=False)
        yield self._table1
        yield Static("│\n│", classes="separator")

        self._table2 = DataTable(show_header=False, zebra_stripes=False)
        yield self._table2
        yield Static("│\n│", classes="separator")

        self._table3 = DataTable(show_header=False, zebra_stripes=False)
        yield self._table3

    def on_mount(self):
        """Set up tables with proper sizing after mount."""
        # Now we have access to self.size
        col_width = self._screen_width // 3

        # Table 1: Expand/Model
        self._col1 = self._table1.add_column("stats1", width=col_width)
        self._row_keys["table1_row1"] = self._table1.add_row("▶ Click to expand")
        self._row_keys["table1_row2"] = self._table1.add_row("Model:")

        # Table 2: Processing/Endpoint
        self._col2 = self._table2.add_column("stats2", width=col_width)
        self._row_keys["table2_row1"] = self._table2.add_row("Processing")
        self._row_keys["table2_row2"] = self._table2.add_row("Endpoint:")

        # Table 3: Tokens/Path
        self._col3 = self._table3.add_column("stats3", width=col_width)
        self._row_keys["table3_row1"] = self._table3.add_row("Tokens:")
        self._row_keys["table3_row2"] = self._table3.add_row("Path:")


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

        import time
        import os.path

        # Table 1 updates: Expand/Model
        self._table1.update_cell(self._row_keys["table1_row1"], self._col1, "▶ Click to expand")
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
        # path_display = os.path.basename(self._path) if self._path else "Unknown"
        self._table3.update_cell(self._row_keys["table3_row2"], self._col3, f"Path:    {self._path}")

    def _update_status_display(self):
        """Update the status display with optional spinner."""
        self._update_all_displays()

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        """Generate CSS for stats dashboard."""
        return f"""
        StatsDashboard {{
            dock: bottom;
            height: 4;
            width: 100%;
            border: solid {theme.box};
            background: {theme.background};
        }}

        StatsDashboard Static {{
            width: 1;
            height: 100%;
        }}

        StatsDashboard DataTable {{
            height: 100%;
            border: none;
        }}
        
        StatsDashboard .separator {{
            width: 1;
            height: 100%;
            border: none;
            color: {theme.box};
            text-align: center;
        }}
        """