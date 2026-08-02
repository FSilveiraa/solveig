"""Async interface layer for Solveig.

`SolveigInterface` (`base.py`) is the display protocol every UI implements:
async display methods (`display_text`/`display_error`/...), input
(`ask_question`/`ask_choice`), scoped output (`with_group`), status/animation
(`set_status`/`with_animation`) and theming (`set_theme`). The conversation
it displays is handed to the root at construction; when a frontend builds its
observer over it is that frontend's own lifecycle problem. Two cross-cutting
concerns live on the protocol deliberately:

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

Deliberately re-exports nothing: `themes` sits below config while `base` sits
above it, so re-exporting both would merge two layers into a single node in the
import graph — `config -> themes` would then drag in the whole protocol. Import
from the real module (`interface.base`, `interface.themes`).
"""
