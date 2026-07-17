"""GroupInterface - the SolveigInterface returned by TerminalInterface's
with_group(). Satisfies the full SolveigInterface contract (a tool body
can't tell it apart from the root), but its local display calls mount into
its own group's container instead of wherever the root currently mounts
content.

Combines `LocalDisplay` (the local display method bodies, shared unchanged
with `TerminalInterface`) with `SolveigInterface` (the root-delegating
global methods) exactly like `TerminalInterface` does - a group never owns
its own `SolveigTextualApp`, spinners, or `pending_queue`, it just borrows
the root's, which `LocalDisplay.__init__` takes directly instead of
constructing them.
"""

from typing import TYPE_CHECKING

from textual.widgets import Collapsible

from solveig.interface.cli.interface import LocalDisplay, TerminalInterface

if TYPE_CHECKING:
    from solveig.interface.cli.collapsible_widgets import CustomCollapsible


class GroupInterface(LocalDisplay):
    def __init__(self, root: "TerminalInterface", group_widget: "CustomCollapsible"):
        self._group_container = group_widget.query_one(Collapsible.Contents)
        super().__init__(
            app=root.app, theme=root.theme, code_theme=root.code_theme, root_ref=root
        )

    @property
    def _container(self):
        return self._group_container
