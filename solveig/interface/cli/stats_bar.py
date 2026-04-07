"""Stats bar - collapsible widget containing stats tables."""

import time
from os import PathLike

from textual.containers import Horizontal
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import DataTable

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
        self._sent_tokens = 0
        self._received_tokens = 0
        self._model = ""
        self._url = ""
        self._path = Filesystem.get_current_directory(simplify=True)
        self._theme = theme
        self.max_context: int | str = 0
        self.used_context = 0
        self.input_price: float = 0
        self.output_price: float = 0
        self.mcp_servers: list[str] = []

    @property
    def tokens(self):
        return f"{self._sent_tokens}↑ / {self._received_tokens}↓"

    @property
    def path(self):
        return f"🗁  {self._path}" if self._path else ""

    @property
    def context(self):
        return f"{self.used_context} / {self.max_context if self.max_context >= 0 else 'Unlimited'}"

    @property
    def price(self):
        return f"${self.input_price}/M↑ / ${self.output_price}/M↓"

    @property
    def mcp(self):
        return (
            "Disconnected"
            if not self.mcp_servers
            else self.mcp_servers[0]
            if len(self.mcp_servers) == 1
            else f"{len(self.mcp_servers)} servers"
        )

    @property
    def status(self):
        status_text = self._status
        if self._spinner:
            frame = self._spinner.render(time.time())
            spinner_char = frame.plain if hasattr(frame, "plain") else str(frame)
            status_text = f"{spinner_char} {status_text}"

        # Format center with theme color, right with folder icon
        return f"[{self._theme.info}]{status_text}[/]" if status_text else ""

    def compose(self):
        """Create collapsible with stats tables."""
        self._collapsible = CustomCollapsible(
            left="Click for more stats",
            center=self.status,
            right=self.path,
            start_collapsed=True,
        )

        with self._collapsible:
            self._table1 = DataTable(
                show_header=False, zebra_stripes=False, classes="stats-table"
            )
            self._table1.add_column("stats1", width=None)

            self._table2 = DataTable(
                show_header=False, zebra_stripes=False, classes="stats-table"
            )
            self._table2.add_column("stats2", width=None)

            # The 3rd table gets a different CSS class to prevent the separator bar
            self._table3 = DataTable(
                show_header=False, zebra_stripes=False, classes="stats-table-final"
            )
            self._table3.add_column("stats3", width=None)

            yield Horizontal(
                self._table1,
                self._table2,
                self._table3,
                classes="stats-container",
            )

    def on_mount(self):
        """Populate tables and title after mount."""
        self._refresh_title()
        self._refresh_stats()

    def update(
        self,
        status: str | None = None,
        sent_tokens: int | None = None,
        received_tokens: int | None = None,
        model: str | None = None,
        url: str | None = None,
        path: str | PathLike | None = None,
        max_context: int | str | None = None,
        used_context: int | None = None,
        input_price: float | None = None,
        output_price: float | None = None,
        mcp_servers: list[str] | None = None,
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

        if sent_tokens is not None:
            self._sent_tokens = sent_tokens
            updated_stats = True

        if received_tokens is not None:
            self._received_tokens = received_tokens
            updated_stats = True

        if model is not None:
            self._model = model
            updated_stats = True

        if url is not None:
            self._url = url
            updated_stats = True

        if max_context is not None:
            self.max_context = max_context
            updated_stats = True

        if used_context is not None:
            self.used_context = used_context
            updated_stats = True

        if input_price is not None:
            self.input_price = input_price
            updated_stats = True

        if output_price is not None:
            self.output_price = output_price
            updated_stats = True

        if mcp_servers is not None:
            self.mcp_servers = mcp_servers
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
        self._collapsible.update_sections(center=self.status, right=self.path)

    def _refresh_stats(self):
        """Rebuild table rows with current values."""
        self._table1.clear()
        self._table2.clear()
        self._table3.clear()

        self._table1.add_row(f"Endpoint: {self._url}")
        self._table1.add_row(f"Tokens: {self.tokens}")
        self._table2.add_row(f"Model: {self._model}")
        self._table2.add_row(f"Context: {self.context}")
        self._table3.add_row(f"MCP: {self.mcp}")
        self._table3.add_row(f"Price: {self.price}")

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

        .stats-table, .stats-table-final {{
            overflow: hidden;
            background: {theme.background};
            color: {theme.text};
        }}

        .stats-table {{
            border-right: solid {theme.box}
        }}

        .stats-table > .datatable--cursor {{
            background: {theme.background};
            color: {theme.text};
        }}

        .stats-table > .datatable--hover {{
            background: {theme.background};
            color: {theme.text};
        }}
        """
