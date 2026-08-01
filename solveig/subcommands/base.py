"""Subcommand — a user-invokable CLI entry point, and the mailbox they arrive in.

A subcommand is the path where a person's typed words become an action WITHOUT
the model: `/config set`, `/read notes.md`, `/help`. It is a sibling of the
agent loop, not a helper for it — both consume what you type, one hands it to an
LLM and the other runs it.

**Push model.** Every source pushes a finished `Subcommand` into `_PENDING` at
import time (a tool's are pushed during bootstrap, once the tool set is known).
The registry reads the list, indexes it, and dispatches. It never goes looking
for subcommands, and it never learns what a config or a tool is.

**One type, no half-built state.** A `Subcommand` always has a handler and
always knows how to parse its own arguments. There is no separate "template"
stage: binding used to mean "attach the app's objects", and the registry can do
that when the command runs, since it holds them for the whole session.

**Signature is the contract.** A handler declares what it needs by annotating
its parameters. Which of them are typed by the user and which are handed over is
decided by `_cli_type` below — the type's own property, so this module never
needs to know which objects the registry happens to hold. That is what keeps it
a leaf: everything in Solveig can declare a subcommand, so it can import almost
nothing back.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, create_model
from pydantic_settings import CliPositionalArg, CliSettingsSource

from solveig.utils.misc import CLI_SETTINGS_OPTS

# `CliPositionalArg[T]` gets applied to types recovered from `inspect.signature`
# at runtime, so the subscript is a value expression, not a type expression -
# there is nothing for a checker to resolve. Naming it through an Any alias says
# that outright, rather than silencing whichever error code mypy raises today.
_Positional: Any = CliPositionalArg

# A parameter is a CLI ARGUMENT when a command line can express its type, and an
# INJECTED DEPENDENCY otherwise. You can type a path, a number or a flag at a
# prompt; you cannot type a SolveigConfig. Deciding it from the type keeps the
# rule here, in the leaf, instead of in a list of "things the registry holds".
_CLI_TYPES: tuple[type, ...] = (str, int, float, bool)
_TYPE_BY_NAME: dict[str, type] = {t.__name__: t for t in _CLI_TYPES}


def _cli_type(annotation: Any) -> type | None:
    """The concrete CLI-expressible type an annotation denotes, or None if the
    parameter has to be injected. Handles the string form too - a module using
    `from __future__ import annotations` hands `inspect` the name, not the
    type."""
    if isinstance(annotation, str):
        return _TYPE_BY_NAME.get(annotation)
    return annotation if annotation in _CLI_TYPES else None


@dataclass
class Subcommand:
    """A user-invokable CLI subcommand: trigger names, `/help` metadata, a
    handler, and the parser for the handler's own arguments.

    Attributes:
        subcommands:   Trigger tokens, e.g. ``["/command", "/cmd"]``. The first
                       is canonical; the rest are aliases, shown together on one
                       ``/help`` line.
        handler:       Async callable. Its annotated parameters are either CLI
                       arguments or dependencies the registry injects by type.
        dependencies:  ``{parameter name: annotation}`` for the injected ones.
        cli_model:     Throwaway pydantic model for the typed ones, or None when
                       the command takes no arguments.
        var_positional: Name of the ``*rest`` parameter, if any - those tokens
                       reach the handler raw, bypassing CLI coercion.
        parameters:    Parameter names in declaration order, so a ``*rest``
                       handler can be called positionally.
        description:   Short ``/help`` blurb.
        usage:         Usage string shown after the names in ``/help``.
        section:       ``/help`` grouping key (``basic``/``config``/``tools``/…).
        is_detail:     Shown indented under its section in ``/help``.
        tool_name:     Set for a tool-backed subcommand, so ``/help`` can mark it
                       ``(disabled)`` when that tool is disabled in config.
        source:        Module this came from. Re-registering a source REPLACES
                       what it contributed, which is what makes plugin reload
                       work - see `register`.
    """

    subcommands: list[str]
    handler: Callable[..., Awaitable[Any]]
    source: str = ""
    dependencies: dict[str, Any] = field(default_factory=dict)
    cli_model: type[BaseModel] | None = None
    var_positional: str | None = None
    parameters: list[str] = field(default_factory=list)
    description: str = ""
    usage: str = ""
    section: str = "basic"
    is_detail: bool = False
    tool_name: str | None = None

    @classmethod
    def from_handler(
        cls,
        handler: Callable[..., Awaitable[Any]],
        *,
        subcommands: list[str],
        section: str = "basic",
        is_detail: bool = False,
        description: str = "",
        usage: str = "",
        tool_name: str | None = None,
    ) -> Subcommand:
        """Read the handler's signature once, at declaration time, and build a
        finished subcommand from it. `usage` overrides the derived string - a
        tool generates a better one from its own fields than a `*tokens`
        signature could suggest."""
        cli_fields: dict[str, Any] = {}
        dependencies: dict[str, Any] = {}
        var_positional: str | None = None
        parameters: list[str] = []

        for name, param in inspect.signature(handler).parameters.items():
            parameters.append(name)
            annotation = param.annotation
            if param.kind is param.VAR_POSITIONAL:
                var_positional = name
                cli_fields[name] = (
                    CliPositionalArg[list[str]],
                    Field(default_factory=list),
                )
                continue
            cli = _cli_type(annotation) if annotation is not param.empty else None
            if cli is None:
                dependencies[name] = annotation
            elif cli is bool and param.default is not param.empty:
                cli_fields[name] = (bool, Field(default=param.default))
            elif param.default is not param.empty:
                cli_fields[name] = (_Positional[cli], Field(default=param.default))
            else:
                cli_fields[name] = (_Positional[cli], Field(default=...))

        return cls(
            subcommands=subcommands,
            handler=handler,
            dependencies=dependencies,
            cli_model=create_model("_Cli", **cli_fields) if cli_fields else None,
            var_positional=var_positional,
            parameters=parameters,
            description=description,
            usage=usage or _usage(cli_fields, var_positional),
            section=section,
            is_detail=is_detail,
            tool_name=tool_name,
        )

    def parse(self, tokens: list[str]) -> dict[str, Any]:
        """Typed arguments from the raw tokens. Raises `SettingsError` /
        `ValidationError`, which the registry turns into an error + usage line -
        one error posture for every subcommand."""
        if self.cli_model is None:
            return {}
        return CliSettingsSource(
            self.cli_model,  # type: ignore[arg-type]
            cli_parse_args=tokens,
            **CLI_SETTINGS_OPTS,
        )()

    def help_line(self, disabled: bool = False) -> str:
        line = ", ".join(self.subcommands)
        if self.usage:
            line += f" {self.usage}"
        if self.description:
            line += f" — {self.description}"
        if disabled:
            line += "  (disabled)"
        return line


# Everything that offers a subcommand pushes one of these here at import time.
_PENDING: list[Subcommand] = []


def subcommand(
    *commands: str,
    section: str = "basic",
    detail: bool = False,
    description: str | None = None,
) -> Callable:
    """Mark an async function as a subcommand handler and push it into
    `_PENDING`. The signature IS the argument spec: parameters whose type a
    command line can express are parsed from what the user typed, the rest are
    injected by the registry. Bool parameters with defaults become
    ``--flag/--no-flag``; ``*rest`` maps to a greedy positional list."""

    def mark(fn: Callable) -> Callable:
        _PENDING.append(
            Subcommand.from_handler(
                fn,
                subcommands=list(commands),
                section=section,
                is_detail=detail,
                description=description
                or ((fn.__doc__ or "").strip().splitlines() or [""])[0],
            )
        )
        return fn

    return mark


# Usage string, derived from the CLI fields so it matches what CliSettingsSource
# will actually accept:
#   required positional → <name>      optional positional → [name]
#   bool flag           → [--name]    *rest               → [name...]
def _usage(fields: dict[str, Any], var_positional: str | None) -> str:
    parts: list[str] = []
    for name, (annotation, default) in fields.items():
        if name == var_positional:
            parts.append(f"[{name}...]")
        elif default is ...:
            parts.append(f"<{name}>")
        elif annotation is bool:
            parts.append(f"[--{name}]")
        else:
            parts.append(f"[{name}]")
    return " ".join(parts)
