"""GroupInterface - the SolveigInterface returned by TerminalInterface's
with_group(). Satisfies the full SolveigInterface contract (a tool body
can't tell it apart from the root), but its local display calls mount into
its own group's container instead of wherever the root currently mounts
content."""

from typing import TYPE_CHECKING

from textual.widgets import Collapsible

from solveig.interface.base import SolveigInterface
from solveig.interface.cli.display_mixin import _ConversationDisplayMixin

if TYPE_CHECKING:
    from solveig.interface.cli.collapsible_widgets import CustomCollapsible
    from solveig.interface.cli.interface import TerminalInterface


class GroupInterface(_ConversationDisplayMixin, SolveigInterface):
    def __init__(self, root: "TerminalInterface", group_widget: "CustomCollapsible"):
        self._root_ref = root
        self.app = root.app
        self.theme = root.theme
        self.code_theme = root.code_theme
        self._group_widget = group_widget
        self._container = group_widget.query_one(Collapsible.Contents)
