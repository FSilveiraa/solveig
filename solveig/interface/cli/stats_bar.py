"""Stats bar - collapsible widget containing stats tables."""

import time
from enum import Enum, auto

from textual.containers import Horizontal
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import DataTable

from solveig.interface.base import SolveigInterface, Stat
from solveig.interface.cli.collapsible_widgets import CustomCollapsible
from solveig.interface.themes import Palette


class Slot(Enum):
    """A place in this bar that is not a table cell.

    An enum rather than a magic tuple or a name: a member has a definition site
    and cannot be typo'd into "unplaced". Only one so far - the collapsible
    header, which is visible while the bar is collapsed and so is where the
    always-relevant stat goes.
    """

    HEADER = auto()


class TextualStat(Stat):
    """A stat plus where this frontend puts it.

    `cell` is Textual's business alone: which table and row a stat occupies -
    or that it belongs in the header instead - is meaningless to a web UI that
    might render the same stats as a side list. Keeping it on the subclass is
    why the interface hands out stats rather than reading them from a registry:
    the frontend that placed one can find it again.

    `None` means "wherever it lands": known stats get known cells (see
    `StatsBar.PLACEMENT`), anything a tool or plugin registers is appended.
    """

    cell: tuple[int, int] | Slot | None = None


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
    PLACEMENT: dict[str, tuple[int, int] | Slot] = {
        "Endpoint": (0, 0),
        "Tokens": (0, 1),
        "Model": (1, 0),
        "Context": (1, 1),
        "MCP": (2, 0),
        "Price": (2, 1),
        # In the header rather than a table: the path is the one stat worth
        # seeing while the bar is collapsed. Otherwise an ordinary stat - a
        # getter, a label, the same refresh - which is why it is placed here
        # instead of being a set_path() the widget keeps its own copy for.
        "Path": Slot.HEADER,
    }

    def __init__(
        self,
        theme: Palette,
        interface_ref: SolveigInterface | None = None,
        config=None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._interface_ref = interface_ref
        self._config = config
        self._timer: Timer | None = None
        self._spinner = None
        self._status = "Initializing"
        self._animation_start: float | None = None
        self._animation_timeout: float | None = None
        self._status_suffix: str | None = None
        self._theme = theme
        #: Registered stats, in registration order. Placement (PLACEMENT) is
        #: applied on add; this list is what a redraw walks.
        self._stats: list[TextualStat] = []

    @property
    def path(self):
        """The header stat's text, read live like any other stat.

        No stored `_path` and no `set_path` writing into one: whoever changes
        the directory calls `refresh_stats()` and the getter reads the new
        value, same as every stat in the tables."""
        for stat in self._stats:
            if stat.cell is Slot.HEADER:
                return stat.text
        return ""

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
            self._table1 = StatsTable(
                show_header=False,
                zebra_stripes=False,
                classes="stats-table",
            )
            self._table1.add_column("stats1", width=None)

            self._table2 = StatsTable(
                show_header=False,
                zebra_stripes=False,
                classes="stats-table",
            )
            self._table2.add_column("stats2", width=None)

            # The 3rd table gets a different CSS class to prevent the separator bar
            self._table3 = StatsTable(
                show_header=False,
                zebra_stripes=False,
                classes="stats-table-final",
            )
            self._table3.add_column("stats3", width=None)

            yield Horizontal(
                self._table1,
                self._table2,
                self._table3,
                classes="stats-container",
            )

    def on_mount(self):
        """Populate tables and title."""
        self._refresh_title()
        self._refresh_stats()

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
                await interface.set_status("This stat isn't editable", duration=2)
            return

        assert stat.on_click is not None  # narrowed by `clickable`
        await stat.on_click()

    def set_status(self, status: str | None) -> None:
        """Set the status line in the collapsible header."""
        self._status = status or ""
        self._refresh_title()

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
        """Rebuild table rows from registered stats, placed by PLACEMENT.

        Tables don't exist until compose() runs (during mount). Stats
        registered before mount are drawn by on_mount's _refresh_stats().
        """
        # A header stat is not in a table, so a table redraw alone would leave
        # it stale. Refreshing the title here means every stat updates on one
        # `refresh_stats()` regardless of where it sits.
        self._refresh_title()

        if not hasattr(self, "_table1"):
            return

        for table in (self._table1, self._table2, self._table3):
            table.clear()
            table.row_stats = []

        # Per-table row lists: (stat | None, display_text). Placed stats fill
        # their designated cells; unplaced stats append to the last table.
        table_rows: list[list[tuple[TextualStat | None, str]]] = [[], [], []]

        for stat in self._stats:
            # A Slot (currently only HEADER) is drawn elsewhere - by
            # _refresh_title, above - so it takes no row here.
            if isinstance(stat.cell, tuple):
                table_idx, row_idx = stat.cell
                rows = table_rows[table_idx]
                while len(rows) <= row_idx:
                    rows.append((None, ""))
                rows[row_idx] = (stat, f"{stat.label}: {stat.text}")

        for stat in self._stats:
            if stat.cell is None:
                table_rows[-1].append((stat, f"{stat.label}: {stat.text}"))

        for table_idx, rows in enumerate(table_rows):
            table = (self._table1, self._table2, self._table3)[table_idx]
            for stat, text in rows:
                table.add_row(text)
                table.row_stats.append(stat)

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
