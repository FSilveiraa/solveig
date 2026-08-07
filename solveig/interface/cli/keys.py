"""The keystrokes this terminal frontend answers to, named once.

NOTE: a hint that names a key is a promise about behaviour. Spelled as a literal
next to a handler that compares its own literal, the two drift and nothing
fails — the status line simply starts lying. So the handlers and the hint read
the same definition here, and `cancel_hint` is DERIVED: change what cancels and
the text changes with it.

Two vocabularies, because there are two cancellations and they are not the same:
a prompt waiting for an answer, and a task already running.
"""

from __future__ import annotations

#: Cancels an in-flight task (a model request, a command). Handled by
#: `SolveigTextualApp.on_key`, which falls through to quitting when nothing is
#: running. Escape is deliberately NOT here: at app level it has no meaning, and
#: claiming it does is what the old hardcoded hint got wrong.
TASK_CANCEL_KEYS: tuple[str, ...] = ("ctrl+c",)

#: Cancels a prompt that is waiting for an answer (a question, a choice).
#: Handled by `InputBar.on_key`, the common ancestor of both input widgets.
PROMPT_CANCEL_KEYS: tuple[str, ...] = ("escape", "ctrl+c")

#: How a key is written for a human. A key with no entry prints as bound.
_KEY_LABELS: dict[str, str] = {
    "escape": "Esc",
    "ctrl+c": "Ctrl+C",
}


def cancel_hint(keys: tuple[str, ...] = TASK_CANCEL_KEYS) -> str:
    """The status-line hint for `keys`, built from the bindings themselves."""
    return f"({'/'.join(_KEY_LABELS.get(key, key) for key in keys)} to cancel)"
