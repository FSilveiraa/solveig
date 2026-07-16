"""Stats bar - collapsible widget containing stats tables."""

import time
from os import PathLike

from textual.containers import Horizontal
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import DataTable

from solveig.exceptions import UserCancel
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
        self._animation_start: float | None = None
        self._animation_timeout: float | None = None
        self._status_suffix: str | None = None
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
        if self._animation_start is not None and self._animation_timeout:
            elapsed = int(time.time() - self._animation_start)
            status_text = f"{status_text} for {elapsed}/{int(self._animation_timeout)}s..."
        if self._status_suffix:
            status_text = f"{status_text} {self._status_suffix}"
        return f"[{self._theme.info}]{status_text}[/]" if status_text else ""

    def compose(self):
        """Create collapsible with stats tables."""
        self._collapsible = CustomCollapsible(
            left_collapsed="Show stats",
            left_expanded="Hide stats",
            center=self.status,
            right=self.path,
            start_collapsed=True,
        )

        with self._collapsible:
            self._table1 = DataTable(
                show_header=False, zebra_stripes=False, classes="stats-table"
            )
            self._table1.add_column("stats1", width=None)
            # Row -> SolveigConfig field edited on click; None = read-only/computed.
            self._table1.row_fields: list[str | None] = ["url", None]

            self._table2 = DataTable(
                show_header=False, zebra_stripes=False, classes="stats-table"
            )
            self._table2.add_column("stats2", width=None)
            self._table2.row_fields: list[str | None] = ["model", "max_context"]

            # The 3rd table gets a different CSS class to prevent the separator bar
            self._table3 = DataTable(
                show_header=False, zebra_stripes=False, classes="stats-table-final"
            )
            self._table3.add_column("stats3", width=None)
            self._table3.row_fields: list[str | None] = [None, None]

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

    async def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Clicking a stat cell opens the equivalent `/config set` prompt, if editable."""
        row_fields = getattr(event.data_table, "row_fields", None)
        field_name = row_fields[event.coordinate.row] if row_fields else None

        interface = getattr(self.app, "_interface_ref", None)
        if interface is None or interface.subcommand_executor is None:
            return

        if field_name is None:
            await interface.update_stats(status="This stat isn't editable", duration=2)
            return

        try:
            await interface.subcommand_executor(
                subcommand=f"/config set {field_name}", interface=interface
            )
        except UserCancel:
            pass

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

    def start_animation_timer(self, timeout: float | None = None) -> None:
        self._animation_start = time.time()
        self._animation_timeout = timeout

    def stop_animation_timer(self) -> None:
        self._animation_start = None
        self._animation_timeout = None

    def set_status_suffix(self, suffix: str | None) -> None:
        self._status_suffix = suffix

    def _refresh_title(self):
        """Update only the collapsible title (lightweight, for frequent spinner updates)."""
        self._collapsible.update_title(center=self.status, right=self.path)

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

        /* Cursor/hover are required for click-to-edit to fire, but shouldn't
           look visually distinct from a normal cell - the cursor position
           (defaulting to row 0) carries no meaning here. */
        .stats-table > .datatable--hover, .stats-table-final > .datatable--hover,
        .stats-table > .datatable--cursor, .stats-table-final > .datatable--cursor {{
            background: {theme.background};
            color: {theme.text};
        }}
        """
