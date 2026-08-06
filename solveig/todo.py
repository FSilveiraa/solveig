"""The todo list — a Solveig concept, not one tool's argument model.

An agent that works autonomously has to be able to say what it intends to do, what
it is doing now, and what it dropped. That plan is Solveig's, the same way a
filesystem entry is (`utils/file.FileMetadata`): `TodoTool` is merely the surface
through which the assistant edits it, as `ReadTool` is a surface over a filesystem
that exists whether or not anyone reads it.

Which is why this sits at layer 0, below both `solveig.tools` and
`solveig.interface`: a frontend receives the todos as values it can draw however it
likes, and neither side depends on the other.

NOTE: the vocabulary here is deliberately NOT ours. `todo`, `todos`, `content`,
`pending`/`in_progress`/`completed`/`cancelled` are what Claude Code, gemini-cli,
qwen-code and Hermes all present to a model, and a model is measurably better at a
tool whose language matches what it has seen everywhere else. Diverging would cost
accuracy and buy nothing but our preference.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class TodoStatus(StrEnum):
    """A todo's state, and the default way to draw it.

    A StrEnum so the LLM schema still shows plain strings while the codebase
    addresses members. The marker is a member attribute rather than a dict keyed by
    the same four strings a second time — a status and its icon are declared once,
    together — and it is *a* default rendering, not *the* rendering: a frontend that
    draws its own glowing orbs is free to ignore it.
    """

    marker: str

    def __new__(cls, value: str, marker: str) -> TodoStatus:
        # NOTE: StrEnum's own __new__ concatenates every argument into the value, so
        # a member carrying a second attribute has to build the str itself and keep
        # `_value_` the bare name the LLM sees.
        status = str.__new__(cls, value)
        status._value_ = value
        status.marker = marker
        return status

    PENDING = ("pending", "⚪")
    IN_PROGRESS = ("in_progress", "🔵")
    COMPLETED = ("completed", "🟢")
    # NOTE: dropped, not attempted-and-broke. gemini-cli, which ships the same
    # member, defines it as "not required anymore due to the dynamic nature of the
    # task" — so a step that failed stays IN_PROGRESS until the assistant decides
    # whether to retry it or drop it.
    CANCELLED = ("cancelled", "⚫")


class TodoItem(BaseModel):
    """One entry in the todo list."""

    content: str = Field(..., description="Clear description of what needs to be done")
    status: TodoStatus = Field(
        default=TodoStatus.PENDING, description="Current status of this todo"
    )
