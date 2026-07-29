"""Async interface layer for Solveig.

`SolveigInterface` (`base.py`) is the display protocol every UI implements:
async display methods (`display_text`/`display_error`/...), input
(`ask_question`/`ask_choice`), scoped output (`with_group`), status/animation
(`update_stats`/`with_animation`), theming (`set_theme`), and the reactive
subscription handshake (`attach_conversation`). Two cross-cutting concerns
live on the protocol deliberately:

- **User-message queue** (`user_message_queue`) — the interface's output
  channel for typed input. The interface `put`s; the queue's prompt gate
  routes /commands before insertion.
- **Cancellation** (`with_cancellable`, the `_active_tasks` registry,
  `cancel_task`, `get_active_tasks`) - every UI with input
  has both a per-operation and a global untargeted cancel, so the registry
  and both verbs are shared protocol, not per-frontend rewrites.

What does NOT live here: prompt serialization policy (each frontend's own,
e.g. the CLI's `_choice_lock`) and command dispatch (the queue gate's).

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
