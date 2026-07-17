"""Async interface layer for Solveig.

`SolveigInterface` (`base.py`) is the abstract contract every UI implements:
async display methods (`display_text`/`display_error`/`display_comment`/...),
input (`ask_question`/`ask_choice`), scoped output (`with_group`), a
cancellable-task stack, and the pending-message queue. The terminal
implementation lives under `cli/` (`TerminalInterface` + its Textual app);
tests supply a `MockInterface`.

Themes (`Palette`, `DEFAULT_THEME`, `DEFAULT_CODE_THEME`) come from `themes.py`.
"""

from solveig.interface.base import SolveigInterface
from solveig.interface.themes import DEFAULT_CODE_THEME, DEFAULT_THEME, Palette

__all__ = [
    "SolveigInterface",
    "Palette",
    "DEFAULT_THEME",
    "DEFAULT_CODE_THEME",
]
