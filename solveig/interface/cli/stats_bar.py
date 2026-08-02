"""Stats bar - collapsible widget containing stats tables."""

import time
from os import PathLike

from textual.containers import Horizontal
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import DataTable

from solveig.interface.base import SolveigInterface, Stat
from solveig.interface.cli.collapsible_widgets import CustomCollapsible
from solveig.interface.themes import Palette
from solveig.utils.file import Filesystem


class TextualStat(Stat):
    """A stat plus where this frontend puts it.

    `cell` is Textual's business alone: which table and row a stat occupies is
    meaningless to a web UI that might render the same stats as a side list.
    Keeping it on the subclass is why the interface hands out stats rather than
    reading them from a registry - the frontend that placed one can find it
    again by identity, instead of matching on a label or trusting registration
    order to line up with a layout table.

    `None` means "wherever it lands": known stats get known cells (see
    `StatsBar.PLACEMENT`), anything a tool or plugin registers is appended.
    """

    cell: tuple[int, int] | None = None


class StatsTable(DataTable):
    """A DataTable that remembers which Stat occupies each row, so a click can
    be routed back to whoever registered it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.row_stats: list[Stat | None] = []


class StatsBar(Widget):
    """Stats bar with collapsible table content.

    Renders whatever stats were registered and routes a click back to the stat's
    owner. It knows where the well-known ones belong and nothing about what they
    mean - no config, no models, no prices."""

    #: Where a well-known stat goes, by label -> (table, row). This frontend's
    #: knowledge alone: the labels come from whoever registers them, but the
    #: layout is Textual's, and a web UI rendering the same stats as a side
    #: list would have no use for it. A stat with no entry here is appended.
    PLACEMENT: dict[str, tuple[int, int]] = {
        "URL": (0, 0),
        "Model": (1, 0),
        "Context": (1, 1),
    }

    def __init__(
        self,
        theme: Palette,
        interface_ref: SolveigInterface | None = None,
        config=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._interface_ref = interface_ref
        self._config = config
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
        #: Registered stats, in registration order. Placement (PLACEMENT) is
        #: applied on add; this list is what a redraw walks.
        self._stats: list[TextualStat] = []

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
            status_text = (
                f"{status_text} for {elapsed}/{int(self._animation_timeout)}s..."
            )
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
            # Row -> SolveigConfig field edited on click; None = read-only/computed.
            self._table1 = StatsTable(
                show_header=False,
                zebra_stripes=False,
                classes="stats-table",
                row_fields=["url", None],
            )
            self._table1.add_column("stats1", width=None)

            self._table2 = StatsTable(
                show_header=False,
                zebra_stripes=False,
                classes="stats-table",
                row_fields=["model", "max_context"],
            )
            self._table2.add_column("stats2", width=None)

            # The 3rd table gets a different CSS class to prevent the separator bar
            self._table3 = StatsTable(
                show_header=False,
                zebra_stripes=False,
                classes="stats-table-final",
                row_fields=[None, None],
            )
            self._table3.add_column("stats3", width=None)

            yield Horizontal(
                self._table1,
                self._table2,
                self._table3,
                classes="stats-container",
            )

    def on_mount(self):
        """Populate tables, title, and subscribe to config for auto-refresh."""
        self._refresh_title()
        self._refresh_stats()

        config = self._config
        if config is not None:

            @config.on_change("api.model", "api.url", "api.max_context")
            async def _on_stats_change(config, paths):
                self.update(
                    model=config.api.model,
                    url=config.api.url,
                    max_context=config.api.max_context,
                )

    def add_stat(self, stat: TextualStat) -> None:
        """Take a stat the interface built and show it.

        Placement is decided HERE, not by the caller: a known stat goes in its
        known cell (`PLACEMENT`), anything else is appended. A caller passing
        coordinates would be a producer deciding a layout it cannot see, and
        would break the moment a frontend arranged things differently."""
        stat.cell = self.PLACEMENT.get(stat.label)
        self._stats.append(stat)
        self.refresh_stats()

    def refresh_stats(self) -> None:
        """Re-read every stat and redraw.

        All of them, not the one that changed: a stat holds no value, so there
        is nothing to hand over, and with a handful of entries re-reading costs
        nothing. Per-stat invalidation is a later refinement."""
        self._refresh_stats()

    async def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Route a click to whoever registered the stat.

        The widget calls a callable and learns nothing about what it does. It
        used to prompt and write to config itself, which meant importing
        `solveig.config.editor` - a frontend reaching up into the domain, and
        the last standing import-linter violation. What to do about a click is
        the stat owner's business (`config/stats.py` builds the closure for a
        config field)."""
        if not isinstance(event.data_table, StatsTable):
            return
        row = event.coordinate.row
        stats = event.data_table.row_stats
        stat = stats[row] if row < len(stats) else None

        if stat is None or not stat.clickable:
            interface = self._interface_ref
            if interface is not None:
                await interface.update_stats(
                    status="This stat isn't editable", duration=2
                )
            return

        assert stat.on_click is not None  # narrowed by `clickable`
        await stat.on_click()

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

    def start_status_animation(
        self, spinner, timeout: float | None = None, suffix: str | None = None
    ) -> None:
        """Start showing `spinner` in the status line, refreshing it 10x/sec
        so the animation actually moves. Owns its own timer end to end - the
        caller doesn't need to hold or manage it."""
        self._spinner = spinner
        self._animation_start = time.time()
        self._animation_timeout = timeout
        self._status_suffix = suffix
        self._refresh_title()
        self._timer = self.set_interval(0.1, self._refresh_title)

    def stop_status_animation(self) -> None:
        """Stop any running animation and clear the status line back to plain text."""
        if self._timer:
            self._timer.stop()
            self._timer = None
        self._spinner = None
        self._animation_start = None
        self._animation_timeout = None
        self._status_suffix = None
        self._refresh_title()

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
    def get_css(cls) -> str:
        """Generate CSS for stats bar."""
        return """
        StatsBar {
            dock: bottom;
            height: auto;
            max-height: 8;
            background: $background;
            color: $foreground;
            border: solid $box;
        }

        /* Stats container responsive layout */
        .stats-container {
            width: 100%;
            height: auto;
        }

        .stats-table, .stats-table-final {
            overflow: hidden;
            background: $background;
            color: $foreground;
        }

        .stats-table {
            border-right: solid $box
        }

        /* Cursor/hover are required for click-to-edit to fire, but shouldn't
           look visually distinct from a normal cell - the cursor position
           (defaulting to row 0) carries no meaning here. */
        .stats-table > .datatable--hover, .stats-table-final > .datatable--hover,
        .stats-table > .datatable--cursor, .stats-table-final > .datatable--cursor {
            background: $background;
            color: $foreground;
        }
        """
