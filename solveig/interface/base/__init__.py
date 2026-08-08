"""The display protocol for Solveig's frontends — re-exports.

All public names live in their own modules and are re-exported here so that
`from solveig.interface.base import X` works regardless of which sub-module
X is defined in.

- `Level`, `Stat`, `SolveigInterface` — interface.py
- `TextBox`, `DiffBox`, `TreeBox`, `EditableMessage` — widgets.py
- `Role` — actions.py
"""

from solveig.interface.base.actions import Role
from solveig.interface.base.interface import Level, SolveigInterface, Stat
from solveig.interface.base.widgets import DiffBox, EditableMessage, TextBox, TreeBox

__all__ = [
    "DiffBox",
    "EditableMessage",
    "Level",
    "Role",
    "SolveigInterface",
    "Stat",
    "TextBox",
    "TreeBox",
]
