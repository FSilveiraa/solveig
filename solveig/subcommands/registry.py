"""SubcommandRegistry — resolves dependencies and dispatches.

The registry is a pure pipe with three jobs: hand a running subcommand the app
objects it asked for, render `/help`, and act as the queue's prompt gate so a
typed `/command` is dispatched instead of being sent to the model.

It does NOT own an index. Lookup goes through `SUBCOMMANDS.subcommands`, a
`ChainMap` view over the per-source stores, so a plugin reload that replaces its
store is visible on the next keystroke with nothing here to invalidate.

It has no domain knowledge - it does not know what a config, an MCP connection
or a tool is. A subcommand arrives already knowing how to parse its own
arguments (`Subcommand.from_handler`, at declaration time); the only thing the
registry adds is the objects that cannot exist until the app is running, which
it matches to parameters BY TYPE. Hence one dispatch path for every subcommand,
whoever declared it.
"""

from __future__ import annotations

import shlex
import warnings
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from pydantic_settings.exceptions import SettingsError

from solveig.api.client import Client
from solveig.config import SolveigConfig
from solveig.exceptions import PluginException, ToolDisabledError, UserCancel
from solveig.interface.base import Level, SolveigInterface
from solveig.session.conversation import Conversation

# NOTE: runtime import, not TYPE_CHECKING - `SessionManager` is a KEY in the
# injectable-deps dict below, i.e. a runtime value, not just an annotation.
# Under TYPE_CHECKING it resolved fine for mypy and raised NameError the moment
# a registry was constructed.
from solveig.session.manager import SessionManager
from solveig.subcommands.base import (
    BUILTIN_SUBCOMMANDS,
    SUBCOMMANDS,
    Subcommand,
    subcommand,
)

if TYPE_CHECKING:
    from solveig.user_message_queue import UserMessageQueue


class UnknownDependency(Exception):
    """A handler asked for a type the registry does not hold.

    A declaration error, not a runtime condition: the injectable set is fixed at
    construction, so a parameter that cannot be filled will never be fillable.
    Handing over `None` instead only moved the failure into the handler, where it
    surfaced as an AttributeError with no mention of the subcommand that caused it.
    """


def _build_sections(subs: list[Subcommand]) -> list[tuple[str, str]]:
    seen = dict.fromkeys(sub.section for sub in subs)
    return [(s, s.replace("_", " ").title()) for s in seen]


class SubcommandRegistry:
    def __init__(
        self,
        config: SolveigConfig,
        conversation: Conversation,
        interface: SolveigInterface,
        client: Client,
        session_manager: SessionManager,
        user_message_queue: UserMessageQueue,
    ) -> None:
        self._config = config
        self._interface = interface
        # What a handler can ask for by annotating a parameter with the type.
        self._deps: dict[type, Any] = {
            SolveigConfig: config,
            Conversation: conversation,
            SolveigInterface: interface,
            Client: client,
            SessionManager: session_manager,
        }
        # Resolve TYPE_CHECKING string annotations: {"SolveigConfig": SolveigConfig, …}
        self._dep_by_name = {k.__name__: k for k in self._deps}
        # /help is self-referential, so it is built here rather than declared:
        # the object that renders it is the one dispatching it. It goes in the
        # built-in store alongside everything `@subcommand` declared.
        SUBCOMMANDS.add(
            BUILTIN_SUBCOMMANDS,
            Subcommand.from_handler(
                self._help_handler,
                subcommands=["/help"],
                description="Show this help.",
            ),
        )
        # NOTE: Self-register as the queue's prompt gate: /commands are
        # dispatched before insertion; prompts pass through unchanged.
        user_message_queue.prompt_handler = self.handle_prompt
        # Report a broken declaration where it can still be tied to whoever made
        # it, rather than when someone happens to type the command. Warn rather
        # than raise: one bad plugin command must not stop the app from starting.
        for sub in SUBCOMMANDS.all():
            for name, annotation in sub.dependencies.items():
                try:
                    self._resolve_dep(annotation)
                except UnknownDependency as err:
                    warnings.warn(
                        f"'{sub.subcommands[0]}' parameter '{name}': {err}",
                        stacklevel=2,
                    )

    async def _help_handler(self) -> None:
        await self.help()

    # ------------------------------------------------------------------
    # Invocation
    # ------------------------------------------------------------------

    def _resolve_dep(self, annotation: Any) -> Any:
        """The app object a handler parameter asked for, matched by type (or by
        name, for a module that stringifies its annotations)."""
        if isinstance(annotation, str):
            annotation = self._dep_by_name.get(annotation, annotation)
        try:
            return self._deps[annotation]
        except (KeyError, TypeError):
            raise UnknownDependency(
                f"No injectable value for {annotation!r}. Injectable types: "
                + ", ".join(sorted(t.__name__ for t in self._deps))
            ) from None

    async def _invoke(self, sub: Subcommand, tokens: list[str]) -> str | None:
        """Parse, fill in the dependencies, call, and hand back whatever the
        handler wants to CONTRIBUTE - text to send on to the assistant, or None
        for a command whose effect was its own (`/config set`, `/help`).

        The single error posture for every subcommand lives here, and that is
        the whole reason a handler does not catch these itself: a parse failure
        shows the message plus the command's own usage line, and a refusal
        (`PluginException` from a `@before_tool` hook, `ToolDisabledError`)
        shows the reason. `_tool_handler` used to duplicate both because it
        parsed its own tokens; it now lets them travel here."""
        # -h/--help short-circuits to a usage line for any subcommand before
        # the handler parses — otherwise argparse (tool path) would print to
        # stdout and raise SystemExit.
        if any(t in ("-h", "--help") for t in tokens):
            await self._interface.print(f"Usage: {sub.help_line()}", level=Level.INFO)
            return None

        try:
            parsed = sub.parse(tokens)
        except (SettingsError, ValidationError) as e:
            await self._interface.print(str(e), level=Level.ERROR)
            await self._interface.print(
                f"Usage: {sub.subcommands[0]} {sub.usage}".rstrip(), level=Level.INFO
            )
            return None

        try:
            injected = {
                name: self._resolve_dep(annotation)
                for name, annotation in sub.dependencies.items()
            }
        except UnknownDependency as err:
            await self._interface.print(str(err), level=Level.ERROR)
            return None

        try:
            return await self._run_handler(sub, injected, parsed, tokens)
        except (PluginException, ToolDisabledError) as err:
            await self._interface.print(str(err), level=Level.ERROR)
            return None

    async def _run_handler(
        self,
        sub: Subcommand,
        injected: dict[str, Any],
        parsed: dict[str, Any],
        tokens: list[str],
    ) -> str | None:
        """Call the handler, positionally when it declares a greedy tail."""
        if sub.var_positional is None:
            return await sub.handler(**injected, **parsed)

        # A *rest handler is called positionally, so the tail can be handed over
        # RAW - CliSettingsSource would coerce it (a trailing "false" becoming a
        # bool), and a greedy tail is exactly the case where the user's literal
        # words matter. Count what the leading parameters consumed to find it.
        leading: list[Any] = []
        consumed = 0
        for name in sub.parameters:
            if name == sub.var_positional:
                break
            if name in injected:
                leading.append(injected[name])
            else:
                leading.append(parsed[name])
                consumed += 1
        return await sub.handler(*leading, *tokens[consumed:])

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _match(self, command_line: str) -> tuple[Subcommand, list[str]] | None:
        """The subcommand this line names and the tokens left over, or None if
        it names none - i.e. it is an ordinary prompt.

        Split from invoking so a caller can tell "not a command" from "a command
        that contributed nothing": both would be a bare None otherwise, and the
        prompt gate has to pass the first through untouched while swallowing
        the second."""
        try:
            tokens = shlex.split(command_line)
        except ValueError:
            tokens = command_line.split()
        if not tokens:
            return None

        # Longest-prefix match, bounded by the longest trigger actually
        # registered rather than a number written here — a three-word command
        # dispatches the day someone declares one.
        for n in range(SUBCOMMANDS.longest_trigger, 0, -1):
            key = " ".join(tokens[:n])
            sub = SUBCOMMANDS.subcommands.get(key)
            if sub is not None:
                return sub, tokens[n:]

        return None

    # ------------------------------------------------------------------
    # Prompt gate — the queue's prompt_handler
    # ------------------------------------------------------------------

    async def handle_prompt(self, text: str) -> str | None:
        """Decide what actually lands on the queue: a prompt passes through
        untouched, a /command runs and contributes whatever it returns.

        A tool subcommand returning its result text is how a `/read` the USER
        ran reaches the assistant - the same channel a typed comment uses, so
        it interleaves into the message being assembled at the next tool
        boundary rather than needing a path of its own. A command with nothing
        to say (`/config set`, `/help`) returns None and is swallowed, which is
        also what a cancelled one does: the user stopped it, so there is
        nothing to report."""
        match = self._match(text)
        if match is None:
            return text  # not a command - an ordinary prompt

        try:
            return await self._invoke(*match) or None
        except UserCancel:
            return None
        except Exception as e:
            await self._interface.print(
                f"Found error when executing '{text}' sub-command: {e}",
                level=Level.ERROR,
            )
            return None

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    async def help(self) -> str:
        help_str = ""
        subcommands = SUBCOMMANDS.all()
        for key, title in _build_sections(subcommands):
            subs = [s for s in subcommands if s.section == key]
            top = [s for s in subs if not s.is_detail]
            details = [s for s in subs if s.is_detail]
            if not top and not details:
                continue
            help_str += f"\n\n{title}:"
            for sub in top:
                help_str += f"\n  • {sub.help_line(disabled=self._is_disabled(sub))}"
            for sub in details:
                help_str += f"\n      {sub.help_line(disabled=self._is_disabled(sub))}"
        await self._interface.add_text_box(help_str, title="Help")
        return help_str

    def _is_disabled(self, sub: Subcommand) -> bool:
        if sub.tool_name is None:
            return False
        return not self._config.is_tool_enabled(sub.tool_name)


@subcommand("/exit", section="basic")
async def exit_app(interface: SolveigInterface) -> None:
    """Exit Solveig."""
    await interface.stop()
