"""Who a message is from, and what can be done to it.

Both halves of what a frontend needs in order to draw a message and offer the
right controls for it - and neither of them is a piece of the conversation. A
frontend that has these does not need the message model, the message's id, or
the conversation it lives in.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    """Who a message is from.

    A `StrEnum` because the value is what a frontend styles with (the terminal
    builds a `role-user` CSS class from it), while the MEMBER is what code
    compares against - so a typo is a `AttributeError` at the definition site
    instead of a comparison that is quietly always false.
    """

    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class MessageActions:
    """What may be done to one message, as callables that already know which
    message they act on.

    An action that does not apply is simply ABSENT, and the frontend renders no
    control for it - which is how "an assistant turn cannot be retried" gets
    expressed without a frontend ever asking what an assistant turn is. The old
    widget decided that with `if self.role == "user"`, i.e. by re-deriving a
    rule it had no business knowing.

    `edit` takes the new text because the frontend owns HOW it is collected (in
    place, a modal, a textarea) and the app owns what the answer means. The rest
    take nothing: the message they refer to was settled when the closure was
    built.

    Refusal lives inside a closure too. An action that cannot run right now (a
    rewind mid-run is undone by the reconciler) reports that itself, so no
    frontend has to learn a rule about when the app is busy.
    """

    edit: Callable[[str], Awaitable[None]] | None = None
    retry: Callable[[], Awaitable[None]] | None = None
    delete: Callable[[], Awaitable[None]] | None = None
    branch: Callable[[], Awaitable[None]] | None = None
