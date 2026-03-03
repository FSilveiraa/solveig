"""Subcommand — a user-invokable CLI entry point.

Can back a Tool (handler + metadata injected by BaseTool.__init_subclass__)
or a plain built-in command (handler passed directly by the runner).

Plugin example::

    class GitTool(BaseTool):
        \"\"\"Run git commands in the repository.\"\"\"

        subcommand: ClassVar[Subcommand] = Subcommand(
            commands=["/git"],
            positional=["git_command"],
        )
        # handler, description, and usage are injected automatically
        # by BaseTool.__init_subclass__ — nothing else required.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from solveig.interface import SolveigInterface


def _parse_cli_args(tokens: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split tokens into (positional_args, keyword_args).

    Tokens matching ``identifier=value`` become kwargs; the rest are positional.
    """
    positional: list[str] = []
    kwargs: dict[str, str] = {}
    for token in tokens:
        if re.match(r"^[a-zA-Z_]\w*=", token):
            k, _, v = token.partition("=")
            kwargs[k] = v
        else:
            positional.append(token)
    return positional, kwargs


@dataclass
class Subcommand:
    """A user-invokable CLI subcommand.

    Stored as a ClassVar on a Tool class or created directly by the runner
    for built-in commands.  The runner completes *handler* before registering.

    Attributes:
        commands:    Trigger tokens, e.g. ``["/git", "/g"]``.  The first is
                     the canonical name shown in ``/help``.
        handler:     Async callable ``(interface, *args, **kwargs)``.
                     ``None`` while stored as a ClassVar template on a tool;
                     always set by the time the subcommand is called.
        positional:  Field names matched to positional CLI tokens by index,
                     used by ``BaseTool.from_cli_args``.
        description: Short human-readable description for ``/help``.
        usage:       Usage string shown after the command names in ``/help``,
                     e.g. ``"<path> [start-end]"``.  Auto-generated from
                     tool model fields when empty.
        is_detail:   If ``True``, shown indented under its section in ``/help``
                     (e.g. ``/config list``, ``/model set``).
    """

    commands: list[str]
    handler: Callable | None = field(default=None, repr=False)
    positional: list[str] = field(default_factory=list)
    description: str = ""
    usage: str = ""
    is_detail: bool = False

    def help_line(self) -> str:
        """Format the single ``/help`` line for this subcommand.

        Example outputs::

            /command, /cmd <command> [timeout=10.0] — Execute a shell command
            /config list — Show all editable fields with current values
        """
        cmds = ", ".join(self.commands)
        parts = [cmds]
        if self.usage:
            parts.append(self.usage)
        line = " ".join(parts)
        if self.description:
            line += f" — {self.description}"
        return line

    async def __call__(self, *tokens: str, interface: SolveigInterface) -> Any:
        """Parse *tokens* and invoke the handler.

        Tokens matching ``key=value`` are separated into kwargs; the rest are
        passed as positional arguments.  ``interface`` is always the handler's
        first positional argument.
        """
        assert self.handler is not None, (
            f"Subcommand {self.commands} has no handler — "
            "it is likely still a ClassVar template that was never registered."
        )
        positional, kwargs = _parse_cli_args(list(tokens))
        return await self.handler(interface, *positional, **kwargs)
