"""Subcommand — a user-invokable CLI entry point.

One concept, two authors. A **tool** declares its args as its model fields and is
parsed by `BaseTool.from_cli_tokens` (→ `CliSettingsSource`); a **built-in** is a
`SubcommandRunner` method whose own SIGNATURE is its arg spec, marked with
`@subcommand` and bound by `bind_tokens`. Both end up as a `handler(interface,
*raw_tokens)`; `Subcommand` itself carries only the trigger names + `/help`
metadata and hands the raw tokens to that handler — no arg parsing of its own.

Built-in arg conventions (read straight off the method signature):
- a parameter without a default → a required positional (`<name>`)
- a parameter with a default    → optional (`[name]`)
- `*rest`                        → greedy tail, e.g. a value that may contain spaces

Plugin/tool example::

    class GitTool(BaseTool):
        \"\"\"Run git commands in the repository.\"\"\"

        subcommand: ClassVar[Subcommand] = Subcommand(commands=["/git"])
        git_command: CliPositionalArg[str] = Field(...)
        # description/usage filled by BaseTool.__pydantic_init_subclass__.

Built-in example::

    @subcommand("/mcp connect", section="mcp", detail=True)
    async def mcp_connect(self, interface, url):
        \"\"\"Connect to an MCP server.\"\"\"
        ...
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from solveig.interface import SolveigInterface


class UsageError(Exception):
    """Raised by `bind_tokens` when the tokens don't fit the handler's signature
    (a required positional is missing, or there are leftover tokens). The caller
    turns it into a usage message."""


def _params_after_interface(handler: Callable) -> list[inspect.Parameter]:
    """The handler's parameters excluding the leading `interface` (a bound method
    has already dropped `self`)."""
    return list(inspect.signature(handler).parameters.values())[1:]


def _coerce(annotation: Any, value: str) -> Any:
    """Coarse token→value coercion for built-in args (almost all plain strings).
    NOTE: bool("false") is truthy in Python, so bools are handled explicitly."""
    if annotation is bool:
        return value.strip().lower() in ("true", "yes", "1", "on")
    if annotation is int:
        return int(value)
    return value


def bind_tokens(handler: Callable, tokens: tuple[str, ...]) -> list[Any]:
    """Bind raw CLI tokens to a handler's positional parameters (after
    `interface`), following the conventions in the module docstring. Returns the
    positional args to call the handler with; raises `UsageError` on a missing
    required arg or leftover tokens."""
    remaining = list(tokens)
    args: list[Any] = []
    for param in _params_after_interface(handler):
        if param.kind is param.VAR_POSITIONAL:  # *rest — greedy tail
            args.extend(remaining)
            remaining = []
            break
        if not remaining:
            if param.default is param.empty:
                raise UsageError  # required positional missing
            break  # optional: let Python apply the default
        args.append(_coerce(param.annotation, remaining.pop(0)))
    if remaining:
        raise UsageError  # too many tokens
    return args


def usage_of(handler: Callable) -> str:
    """Derive a `/help` usage string from the handler signature: `<name>` for a
    required positional, `[name]` for optional, `[name...]` for a `*rest` tail."""
    parts = []
    for param in _params_after_interface(handler):
        if param.kind is param.VAR_POSITIONAL:
            parts.append(f"[{param.name}...]")
        elif param.default is not param.empty:
            parts.append(f"[{param.name}]")
        else:
            parts.append(f"<{param.name}>")
    return " ".join(parts)


def first_docline(handler: Callable) -> str:
    """The first line of the handler's docstring — its `/help` blurb."""
    doc = (handler.__doc__ or "").strip()
    return doc.splitlines()[0] if doc else ""


@dataclass
class _SubcommandMark:
    """What `@subcommand` stamps onto a method; the runner reads it during
    discovery to build the `Subcommand`."""

    commands: list[str]
    section: str
    is_detail: bool
    description: str | None


def subcommand(
    *commands: str,
    section: str = "basic",
    detail: bool = False,
    description: str | None = None,
) -> Callable:
    """Mark a `SubcommandRunner` method as a built-in subcommand. The method's
    signature is its arg spec (see `bind_tokens`); discovery turns each marked
    method into a `Subcommand`. Extra `commands` are aliases and render on the
    same `/help` line. `description` defaults to the method's first docstring line.
    """

    def mark(fn: Callable) -> Callable:
        fn._subcommand = _SubcommandMark(  # type: ignore[attr-defined]
            commands=list(commands),
            section=section,
            is_detail=detail,
            description=description,
        )
        return fn

    return mark


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
        """Format the single ``/help`` line, joining every alias in ``commands``.

        Example: ``/command, /cmd <command> [timeout] — Execute a shell command``
        """
        line = ", ".join(self.commands)
        if self.usage:
            line += f" {self.usage}"
        if self.description:
            line += f" — {self.description}"
        if disabled:
            line += "  (disabled)"
        return line

    async def __call__(self, *tokens: str, interface: SolveigInterface) -> Any:
        """Hand the raw tokens to the handler. `-h`/`--help` short-circuits to a
        usage line for *any* subcommand (built-in or tool) before the handler
        parses — otherwise argparse (on the tool path) would print to stdout and
        raise SystemExit. `interface` is always the handler's first argument."""
        assert self.handler is not None, (
            f"Subcommand {self.commands} has no handler — "
            "it is likely still a ClassVar template that was never registered."
        )
        if any(token in ("-h", "--help") for token in tokens):
            await interface.display_info(f"Usage: {self.help_line()}")
            return None
        return await self.handler(interface, *tokens)
