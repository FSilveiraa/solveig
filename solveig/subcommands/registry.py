"""SubcommandRegistry — reads `_PENDING`, binds handlers, dispatches.

The registry is a pure pipe: it receives a deps dict at construction, reads the
module-level `_PENDING` list (populated at import time by `@subcommand` and tool
`__pydantic_init_subclass__`), builds one handler per template, and exposes a
single `__call__` for dispatch. No domain knowledge — it doesn't know what a
config or an MCP connection is.

One CLI parsing path: CliSettingsSource for everything. Built-in handler params
become a throwaway pydantic model (required positional → CliPositionalArg[T],
bool with default → --flag/--no-flag, *rest → list[str]).
"""

from __future__ import annotations

import inspect
import shlex
from typing import Any

from pydantic import Field, ValidationError, create_model
from pydantic_settings import CliPositionalArg, CliSettingsSource
from pydantic_settings.exceptions import SettingsError

from solveig.config import SolveigConfig
from solveig.exceptions import PluginException, ToolDisabledError
from solveig.interface import SolveigInterface
from solveig.subcommands.base import (
    _PENDING,
    Subcommand,
    _SubcommandTemplate,
    subcommand,
)
from solveig.tools.orchestration import run_tool_and_hooks


def _build_sections(subs: list[Subcommand]) -> list[tuple[str, str]]:
    seen = dict.fromkeys(sub.section for sub in subs)
    return [(s, s.replace("_", " ").title()) for s in seen]


# Options for CliSettingsSource — same as tools/base.py:CLI_PARSE_OPTS
_CLI_OPTS: dict[str, Any] = {
    "cli_exit_on_error": False,
    "cli_implicit_flags": True,
    "cli_kebab_case": False,
    "case_sensitive": True,
    "cli_enforce_required": False,
}


class SubcommandRegistry:
    def __init__(self, deps: dict[type, Any]):
        self._deps = deps
        # Resolve TYPE_CHECKING string annotations: {"SolveigConfig": SolveigConfig, …}
        self._dep_by_name = {k.__name__: k for k in deps}
        self._registry: dict[str, Subcommand] = {}
        self._subcommands: list[Subcommand] = []
        self._bind_all()

    # ------------------------------------------------------------------
    # Binding
    # ------------------------------------------------------------------

    def _bind_all(self) -> None:
        for template in _PENDING:
            if template.tool_cls is not None:
                sub = self._bind_tool(template)
            else:
                sub = self._bind_builtin(template)
            self._register(sub)

        # /help is self-referential — the registry owns its own help display.
        # Not pushed through _PENDING since it's the same object dispatching it.
        async def _help_handler(interface: SolveigInterface, *tokens: str) -> None:
            await self.help(interface)

        self._register(
            Subcommand(
                commands=["/help"],
                handler=_help_handler,
                description="List available commands",
                section="basic",
            )
        )

    def _register(self, sub: Subcommand) -> None:
        self._subcommands.append(sub)
        for command in sub.commands:
            self._registry[command] = sub

    # ------------------------------------------------------------------
    # Injection detection
    # ------------------------------------------------------------------
    # A parameter is injected (not CLI-parsed) when its annotation is:
    #   - SolveigInterface (universal dispatcher param, always passed by handler)
    #   - A key in self._deps (resolved via _dep_by_name for TYPE_CHECKING strings)
    #   - inspect.Parameter.empty (unannotated, treated as injected)

    def _is_injected(self, ann: Any) -> bool:
        if ann is inspect.Parameter.empty:
            return True
        if ann is SolveigInterface:
            return True
        if isinstance(ann, str):
            return ann == "SolveigInterface" or ann in self._dep_by_name
        return ann in self._deps

    def _resolve_dep(self, ann: Any) -> Any:
        """Return the dep value for an annotation (class or string), or None."""
        if isinstance(ann, str):
            cls = self._dep_by_name.get(ann)
            return self._deps[cls] if cls else None
        return self._deps.get(ann)

    # ------------------------------------------------------------------
    # Built-in handler binding — CliSettingsSource for everything.
    # ------------------------------------------------------------------
    #
    # Signature → throwaway pydantic model:
    #   field: str             → CliPositionalArg[str], required
    #   field: str = ""        → CliPositionalArg[str], optional
    #   field: bool = False    → bool, --field/--no-field
    #   *rest: str             → list[str], greedy positional

    def _bind_builtin(self, template: _SubcommandTemplate) -> Subcommand:
        assert template.fn is not None
        sig = inspect.signature(template.fn)

        cli_fields: dict[str, tuple[type, Any]] = {}
        injected_names: list[str] = []
        var_positional_name: str | None = None

        for name, param in sig.parameters.items():
            ann = param.annotation
            if self._is_injected(ann):
                injected_names.append(name)
            elif param.kind == param.VAR_POSITIONAL:
                var_positional_name = name
                cli_fields[name] = (
                    CliPositionalArg[list[str]],  # type: ignore[valid-type]
                    Field(default_factory=list),
                )
            elif ann is bool and param.default is not param.empty:
                cli_fields[name] = (bool, Field(default=param.default))
            elif param.default is not param.empty:
                cli_fields[name] = (
                    CliPositionalArg[ann],  # type: ignore[valid-type]
                    Field(default=param.default),
                )
            else:
                cli_fields[name] = (
                    CliPositionalArg[ann],  # type: ignore[valid-type]
                    Field(default=...),
                )

        usage = _builtin_usage(cli_fields, var_positional_name)
        CliModel = create_model("_Cli", **cli_fields) if cli_fields else None

        async def handler(interface: SolveigInterface, *tokens: str) -> None:
            parsed: dict[str, Any] = {}
            if CliModel:
                try:
                    parsed = CliSettingsSource(
                        CliModel,  # type: ignore[arg-type]
                        cli_parse_args=list(tokens),
                        **_CLI_OPTS,
                    )()
                except (SettingsError, ValidationError) as e:
                    await interface.display_error(str(e))
                    await interface.display_info(
                        f"Usage: {template.commands[0]} {usage}".rstrip()
                    )
                    return

            # Build final kwargs: interface + injected deps + CLI args
            kwargs: dict[str, Any] = {"interface": interface}
            for name in injected_names:
                ann = sig.parameters[name].annotation
                if ann is SolveigInterface or (
                    isinstance(ann, str) and ann == "SolveigInterface"
                ):
                    continue  # already set by the dispatcher
                kwargs[name] = self._resolve_dep(ann)

            # Merge parsed CLI args (except var-positional) into kwargs
            all_kwargs = dict(kwargs)
            for name, value in parsed.items():
                if name != var_positional_name:
                    all_kwargs[name] = value

            if var_positional_name is None:
                await template.fn(**all_kwargs)
            else:
                # Build leading positional args in signature order up to
                # the *rest param.  Count consumed tokens to slice raw
                # tokens for *rest (bypassing CliSettingsSource bool coercion).
                leading: list[Any] = []
                consumed = 0
                for pname in sig.parameters:
                    if pname == var_positional_name:
                        break
                    if pname in injected_names:
                        leading.append(kwargs[pname])
                    else:
                        leading.append(all_kwargs[pname])
                        consumed += 1
                await template.fn(*leading, *tokens[consumed:])

        return Subcommand(
            commands=template.commands,
            handler=handler,
            description=template.description,
            usage=usage,
            section=template.section,
            is_detail=template.is_detail,
        )

    # ------------------------------------------------------------------
    # Tool handler binding
    # ------------------------------------------------------------------

    def _bind_tool(self, template: _SubcommandTemplate) -> Subcommand:
        assert template.tool_cls is not None
        cls = template.tool_cls
        tool_template = cls.subcommand

        async def handler(interface: SolveigInterface, *tokens: str) -> None:
            try:
                instance = cls.from_cli_tokens(list(tokens))
            except (SettingsError, ValidationError) as e:
                await interface.display_error(str(e))
                await interface.display_info(f"Usage: {tool_template.help_line()}")
                return
            try:
                config = self._deps[SolveigConfig]
                await run_tool_and_hooks(instance, config, interface)
            except (PluginException, ToolDisabledError) as e:
                await interface.display_error(str(e))

        return Subcommand(
            commands=template.commands,
            handler=handler,
            description=tool_template.description,
            usage=tool_template.usage,
            section="tools",
            is_detail=tool_template.is_detail,
            tool_name=cls.tool_name(),
        )

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def __call__(self, command_line: str, interface: SolveigInterface) -> bool:
        try:
            tokens = shlex.split(command_line)
        except ValueError:
            tokens = command_line.split()
        if not tokens:
            return False

        for n in (2, 1):
            key = " ".join(tokens[:n])
            if key in self._registry:
                await self._registry[key](*tokens[n:], interface=interface)
                return True

        return False

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    async def help(self, interface: SolveigInterface) -> str:
        help_str = ""
        for key, title in _build_sections(self._subcommands):
            subs = [s for s in self._subcommands if s.section == key]
            top = [s for s in subs if not s.is_detail]
            details = [s for s in subs if s.is_detail]
            if not top and not details:
                continue
            help_str += f"\n\n{title}:"
            for sub in top:
                help_str += f"\n  • {sub.help_line(disabled=self._is_disabled(sub))}"
            for sub in details:
                help_str += f"\n      {sub.help_line(disabled=self._is_disabled(sub))}"
        await interface.display_text_box(help_str, title="Help")
        return help_str

    def _is_disabled(self, sub: Subcommand) -> bool:
        config = self._deps.get(SolveigConfig)
        if config is None or sub.tool_name is None:
            return False
        return not config.is_tool_enabled(sub.tool_name)


# -------------------------------------------------------------------
# Usage string — derived from the CliModel fields, not the signature.
# This must match what CliSettingsSource will accept.
# -------------------------------------------------------------------
#   CliPositionalArg[ann] → <name> (required) or [name] (optional)
#   bool                 → [--name]
#   list[str]             → [name...]
#   Anything else         → [--name <name>]


def _builtin_usage(
    fields: dict[str, tuple[type, Any]], var_positional_name: str | None
) -> str:
    parts: list[str] = []
    for name, (_ann, default) in fields.items():
        if name == var_positional_name:
            parts.append(f"[{name}...]")
        elif default is ...:
            parts.append(f"<{name}>")
        elif _ann is bool:
            parts.append(f"[--{name}]")
        else:
            parts.append(f"[{name}]")
    return " ".join(parts)


@subcommand("/exit", section="basic")
async def exit_app(interface: SolveigInterface) -> None:
    """Exit Solveig."""
    await interface.stop()
