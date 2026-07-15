"""GroupInterface - the SolveigInterface returned by TerminalInterface's
with_group(). Satisfies the full SolveigInterface contract (a tool body
can't tell it apart from the root), but its local display calls mount into
its own group's container instead of wherever the root currently mounts
content.

Inherits TerminalInterface's local display method bodies as-is (they only
ever read self._container/self.app/self.theme/self.code_theme) and
deliberately skips TerminalInterface.__init__ - a group never owns its own
SolveigTextualApp, spinners, or pending_queue, it just borrows the root's.
"""

from typing import TYPE_CHECKING

from textual.widgets import Collapsible

from solveig.interface.cli.interface import TerminalInterface

if TYPE_CHECKING:
    from solveig.interface.cli.collapsible_widgets import CustomCollapsible


class GroupInterface(TerminalInterface):
    def __init__(self, root: "TerminalInterface", group_widget: "CustomCollapsible"):
        # Deliberately not calling super().__init__() - see module docstring.
        self._root_ref = root
        self.app = root.app
        self.theme = root.theme
        self.code_theme = root.code_theme
        self._group_widget = group_widget
        self._group_container = group_widget.query_one(Collapsible.Contents)

    @property
    def _container(self):
        return self._group_container
