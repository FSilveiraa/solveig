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

from dataclasses import dataclass


@dataclass(frozen=True)
class Key:
    keystroke: str
    label: str

class Keys(set[Key]):
    _label_to_key: dict[str, Key] = {}

    def __add__(self, key: str | Key) -> Key:
        key = Key()
        return super().__add__()

    def __contains__(self, key: str | Key) -> bool:
        if isinstance(key, str):
            return any(key)

# Cancel a question, clear a prompt or cancel running tasks
CANCEL_KEYS: dict[str, Key] = { "escape", "ctrl+c" }
# Quit the application
QUIT_KEYS: set[Key] = { "ctrl+c" }

# How a key is written for a human. A key with no entry prints as bound.
_KEY_LABELS: dict[str, str] = {
    "escape": "Esc",
    "ctrl+c": "Ctrl+C",
}


def cancel_hint(keys: tuple[str, ...] = CANCEL_KEYS) -> str:
    """The status-line hint for `keys`, built from the bindings themselves."""
    return f"({'/'.join(_KEY_LABELS.get(key, key) for key in keys)} to cancel)"
