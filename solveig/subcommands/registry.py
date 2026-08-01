"""SubcommandRegistry — indexes `_PENDING`, resolves dependencies, dispatches.

The registry is a pure pipe with four jobs: index the pushed subcommands by
their trigger words, hand a running subcommand the app objects it asked for,
render `/help`, and act as the queue's prompt gate so a typed `/command` is
dispatched instead of being sent to the model.

It has no domain knowledge - it does not know what a config, an MCP connection
or a tool is. A subcommand arrives already knowing how to parse its own
arguments (`Subcommand.from_handler`, at declaration time); the only thing the
registry adds is the objects that cannot exist until the app is running, which
it matches to parameters BY TYPE. Hence one dispatch path for every subcommand,
whoever declared it.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from pydantic_settings.exceptions import SettingsError

from solveig.api.client import Client
from solveig.config import SolveigConfig
from solveig.exceptions import UserCancel
from solveig.interface.base import SolveigInterface
from solveig.session.conversation import Conversation
from solveig.subcommands.base import _PENDING, Subcommand, subcommand

if TYPE_CHECKING:
    from solveig.session.manager import SessionManager
    from solveig.user_message_queue import UserMessageQueue


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
        self._registry: dict[str, Subcommand] = {}
        self._subcommands: list[Subcommand] = []
        self._index()
        # HACK: Self-register as the queue's prompt gate: /commands are
        # dispatched before insertion; prompts pass through unchanged.
        user_message_queue.prompt_handler = self.handle_prompt

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def _index(self) -> None:
        for sub in _PENDING:
            self._register(sub)

        # /help is self-referential, so it is built here rather than pushed:
        # the object that renders it is the one dispatching it.
        self._register(
            Subcommand.from_handler(
                self._help_handler,
                subcommands=["/help"],
                description="Show this help.",
            )
        )

    async def _help_handler(self) -> None:
        await self.help()

    def _register(self, sub: Subcommand) -> None:
        self._subcommands.append(sub)
        for name in sub.subcommands:
            self._registry[name] = sub

    # ------------------------------------------------------------------
    # Invocation
    # ------------------------------------------------------------------

    def _resolve_dep(self, annotation: Any) -> Any:
        """The app object a handler parameter asked for, matched by type (or by
        name, for a module that stringifies its annotations)."""
        if isinstance(annotation, str):
            cls = self._dep_by_name.get(annotation)
            return self._deps[cls] if cls else None
        return self._deps.get(annotation)

    async def _invoke(self, sub: Subcommand, tokens: list[str]) -> None:
        """Parse, fill in the dependencies, call. The single error posture for
        every subcommand lives here: a parse failure shows the message and the
        command's own usage line."""
        try:
            parsed = sub.parse(tokens)
        except (SettingsError, ValidationError) as e:
            await self._interface.display_error(str(e))
            await self._interface.display_info(
                f"Usage: {sub.subcommands[0]} {sub.usage}".rstrip()
            )
            return

        injected = {
            name: self._resolve_dep(annotation)
            for name, annotation in sub.dependencies.items()
        }

        if sub.var_positional is None:
            await sub.handler(**injected, **parsed)
            return

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
        await sub.handler(*leading, *tokens[consumed:])

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def __call__(self, command_line: str) -> bool:
        try:
            tokens = shlex.split(command_line)
        except ValueError:
            tokens = command_line.split()
        if not tokens:
            return False

        for n in (2, 1):
            key = " ".join(tokens[:n])
            if key in self._registry:
                sub = self._registry[key]
                remaining = tokens[n:]
                # -h/--help short-circuits to a usage line for any subcommand
                # before the handler parses — otherwise argparse (tool path)
                # would print to stdout and raise SystemExit.
                if any(t in ("-h", "--help") for t in remaining):
                    await self._interface.display_info(f"Usage: {sub.help_line()}")
                    return True
                await self._invoke(sub, remaining)
                return True

        return False

    # ------------------------------------------------------------------
    # Prompt gate — the queue's prompt_handler
    # ------------------------------------------------------------------

    async def handle_prompt(self, text: str) -> str | None:
        """Run /commands through the executor, pass prompts through unchanged.
        Returns the (possibly transformed) text to enqueue, or None to
        swallow (was a /command, already dispatched)."""
        try:
            if await self(text):
                return None
        except UserCancel:
            return None
        except Exception as e:
            await self._interface.display_error(
                f"Found error when executing '{text}' sub-command: {e}"
            )
            return None
        return text

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    async def help(self) -> str:
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
        await self._interface.display_text_box(help_str, title="Help")
        return help_str

    def _is_disabled(self, sub: Subcommand) -> bool:
        if sub.tool_name is None:
            return False
        return not self._config.is_tool_enabled(sub.tool_name)


@subcommand("/exit", section="basic")
async def exit_app(interface: SolveigInterface) -> None:
    """Exit Solveig."""
    await interface.stop()
