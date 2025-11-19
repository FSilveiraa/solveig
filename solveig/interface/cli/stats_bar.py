"""Stats bar - just the table content."""

from textual.widgets import DataTable, Static
from textual.containers import Horizontal


def create_stats_content():
    """Create the three tables and separators for use in a Collapsible."""
    table1 = DataTable(show_header=False, zebra_stripes=False)
    table1.add_column("Col1")
    table1.add_row("Test 1A")
    table1.add_row("Test 1B")

    table2 = DataTable(show_header=False, zebra_stripes=False)
    table2.add_column("Col2")
    table2.add_row("Test 2A")
    table2.add_row("Test 2B")

    table3 = DataTable(show_header=False, zebra_stripes=False)
    table3.add_column("Col3")
    table3.add_row("Test 3A")
    table3.add_row("Test 3B")

    return Horizontal(
        table1,
        Static("│\n│", classes="separator"),
        table2,
        Static("│\n│", classes="separator"),
        table3
    )