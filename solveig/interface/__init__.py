"""Interface layer for Solveig.

`SolveigInterface` (`base/interface.py`) is the display protocol every UI
implements: text output (`print`), complex rendering (`display_tree`,
`display_diff` returning box handles), input (`ask_question`/`ask_choice`),
scoped output (`with_group`), status/animation, and theming. The conversation
it displays is handed to the root at construction.

Two cross-cutting concerns live on the protocol deliberately:

- **User-message queue** (`user_message_queue`) — the interface's output
  channel for typed input.
- **Cancellation** (`with_cancellable`, `_active_tasks`, `cancel_task`) —
  every UI with input has both a per-operation and a global untargeted cancel.

The terminal implementation lives under `cli/` (`TerminalInterface` + its
Textual app); tests supply a `MockInterface`.

Themes (`Palette`, `DEFAULT_THEME`, `DEFAULT_CODE_THEME`) come from `themes.py`.

Deliberately re-exports nothing: `themes` sits below config while `base` sits
above it, so re-exporting both would merge two layers into a single node in the
import graph — `config -> themes` would then drag in the whole protocol. Import
from the real module (`interface.base`, `interface.themes`).
"""
