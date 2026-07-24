"""Async interface layer for Solveig.

`SolveigInterface` (`base.py`) is the display protocol every UI implements:
async display methods (`display_text`/`display_error`/...), input
(`ask_question`/`ask_choice`), scoped output (`with_group`), status/animation
(`update_stats`/`with_animation`), theming (`set_theme`), and the reactive
subscription handshake (`attach_conversation`). Two cross-cutting concerns
live on the protocol deliberately:

- **Producer callbacks** (`on_user_input`, `on_edit_config_field`) - the
  interface never names app objects (runner, Inbox); run.py wires these at
  construction to the session's input routing (decision D5).
- **Cancellation** (`with_cancellable`, `cancel_operation`,
  `cancel_active_operation`, `has_active_operations`) - every UI with input
  has both a per-operation and a global untargeted cancel, so the registry
  and both verbs are shared protocol, not per-frontend rewrites.

What does NOT live here: the input queue itself (the session Inbox is owned
by run.py's main loop - `solveig/inbox.py`), prompt serialization policy
(the CLI's `_choice_lock`), and command dispatch (the SubcommandRunner).

The terminal implementation lives under `cli/` (`TerminalInterface` + its
Textual app); tests supply a `MockInterface`.

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
