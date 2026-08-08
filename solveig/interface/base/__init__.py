"""The display protocol for Solveig's frontends — re-exports.

All public names live in their own modules and are re-exported here so that
`from solveig.interface.base import X` works regardless of which sub-module
X is defined in.

- `Level`, `Stat`, `SolveigInterface` — interface.py
- `TextBox`, `DiffBox`, `TreeBox`, `MessageBox`, `EditableMessage` — widgets.py
- `Role`, `MessageActions` — actions.py
"""

from solveig.interface.base.actions import MessageActions, Role
from solveig.interface.base.interface import Level, SolveigInterface, Stat
from solveig.interface.base.widgets import (
    DiffBox,
    EditableMessage,
    MessageBox,
    TextBox,
    TreeBox,
)

__all__ = [
    "DiffBox",
    "EditableMessage",
    "Level",
    "MessageActions",
    "MessageBox",
    "Role",
    "SolveigInterface",
    "Stat",
    "TextBox",
    "TreeBox",
]
