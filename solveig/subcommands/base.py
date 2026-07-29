"""Subcommand — a user-invokable CLI entry point.

Push model: every subcommand source pushes a template into `_PENDING` at import
time. The registry reads the list, builds handlers (inspect signature → inject
deps → build CliSettingsSource parser → bind), and dispatches. No fetch, no
iterate, no two-author split in the dispatch path.

- **Built-in** — `@subcommand` on a plain function. Signature is the contract:
  injected params (matched by type) and CLI params (CliSettingsSource-parsed).
- **Tool** — `Subcommand` ClassVar on a `BaseTool`. Pushes with `tool_cls` set;
  the registry binds a handler that parses → instantiates → orchestrates.
- **Plugin** — same `@subcommand` decorator, same list. No special path.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Push-model pending list — everything pushes here at import time
# ---------------------------------------------------------------------------


@dataclass
class _SubcommandTemplate:
    """What a subcommand source pushes into `_PENDING`. `fn` and `tool_cls` are
    mutually exclusive: a built-in/plugin sets `fn`, a tool sets `tool_cls`."""

    fn: Callable | None = None
    tool_cls: type | None = None
    commands: list[str] = field(default_factory=list)
    section: str = "basic"
    is_detail: bool = False
    description: str = ""


_PENDING: list[_SubcommandTemplate] = []


# ---------------------------------------------------------------------------
# @subcommand decorator — inspect signature, push to _PENDING
# ---------------------------------------------------------------------------


def subcommand(
    *commands: str,
    section: str = "basic",
    detail: bool = False,
    description: str | None = None,
) -> Callable:
    """Mark a function as a subcommand handler. The signature IS the arg spec:
    params whose type matches a registry dep are injected; everything else is
    CLI-parsed via CliSettingsSource.  Bool params with defaults become
    ``--flag/--no-flag``; ``*rest`` maps to a greedy positional list.

    Pushes a `_SubcommandTemplate` into `_PENDING` at import time — the
    registry reads this list later.
    """

    def mark(fn: Callable) -> Callable:
        desc = description or ((fn.__doc__ or "").strip().splitlines()[0])
        _PENDING.append(
            _SubcommandTemplate(
                fn=fn,
                commands=list(commands),
                section=section,
                is_detail=detail,
                description=desc,
            )
        )
        return fn

    return mark


# ---------------------------------------------------------------------------
# Subcommand — the runtime dispatch object (same shape for every path)
# ---------------------------------------------------------------------------


@dataclass
class Subcommand:
    """A user-invokable CLI subcommand: trigger names + `/help` metadata + a
    handler that consumes the raw token list.

    Attributes:
        commands:    Trigger tokens, e.g. ``["/session store", "/store"]``. The
                     first is canonical; the rest are aliases, shown together on
                     one ``/help`` line.
        handler:     Async callable ``(interface, *raw_tokens)``. ``None`` while a
                     tool's ClassVar template awaits the runner binding a handler.
        description: Short ``/help`` blurb.
        usage:       Usage string after the names in ``/help`` (``<x> [y]``).
        section:     ``/help`` grouping key (``basic``/``config``/``model``/…).
        is_detail:   Shown indented under its section in ``/help`` when ``True``.
        tool_name:   Set for a tool-backed subcommand, so ``/help`` can mark it
                     ``(disabled)`` when that tool is disabled in config.
    """

    commands: list[str]
    handler: Callable | None = field(default=None, repr=False)
    description: str = ""
    usage: str = ""
    section: str = "basic"
    is_detail: bool = False
    tool_name: str | None = None

    def help_line(self, disabled: bool = False) -> str:
        line = ", ".join(self.commands)
        if self.usage:
            line += f" {self.usage}"
        if self.description:
            line += f" — {self.description}"
        if disabled:
            line += "  (disabled)"
        return line

    async def __call__(self, *tokens: str) -> Any:
        """Hand the raw tokens to the handler."""
        assert self.handler is not None, (
            f"Subcommand {self.commands} has no handler — "
            "it is likely still a ClassVar template that was never registered."
        )
        return await self.handler(*tokens)
