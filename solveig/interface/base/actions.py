"""Who a message is from, and what can be done to it.

Both halves of what a frontend needs in order to draw a message and offer the
right controls for it - and neither of them is a piece of the conversation. A
frontend that has these does not need the message model, the message's id, or
the conversation it lives in.
"""

from __future__ import annotations

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
