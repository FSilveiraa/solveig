"""SubcommandRunner — dispatches user-typed /commands to registered handlers.

Two authoring paths, one registry. A **built-in** command is an `@subcommand`-
marked method whose signature is its arg spec (discovered at init via
`_discover_builtins`); a **tool** command comes from each tool's `Subcommand`
ClassVar (`_register_tool_subcommands`). Both become `Subcommand` entries in one
flat lookup and are dispatched identically — see `subcommand/base.py` for the
one-concept/two-authors design.
"""

from __future__ import annotations

import dataclasses
import os
import re
import shlex
from collections.abc import Callable

from pydantic import ByteSize, SecretStr, ValidationError
from pydantic_settings.exceptions import SettingsError

from solveig.api import ProviderRef
from solveig.config import DEFAULT_CONFIG_PATHS, MCPServerConfig, SolveigConfig, sources
from solveig.config.editor import (
    editable_fields,
    get_config_value,
    parse_config_value,
    prompt_for_field,
)
from solveig.config.runtime_effects import fetch_and_apply_model_info
from solveig.conversation import Conversation
from solveig.exceptions import PluginException, ToolDisabledError
from solveig.interface import SolveigInterface
from solveig.mcp_servers import MCP_CONNECTIONS
from solveig.mcp_servers.client import connect, disconnect, find_connection
from solveig.sessions.manager import SessionManager
from solveig.subcommand.base import (
    Subcommand,
    UsageError,
    bind_tokens,
    subcommand,
    usage_of,
)
from solveig.tools.available import tool_classes
from solveig.tools.base import BaseTool
from solveig.tools.orchestration import run_tool_and_hooks
from solveig.utils.misc import format_age


def _build_sections(subs: list[Subcommand]) -> list[tuple[str, str]]:
    """Derive /help sections from the registered subcommands — no hand-kept
    list that drifts when someone adds a new section."""
    seen = dict.fromkeys(sub.section for sub in subs)
    return [(s, s.replace("_", " ").title()) for s in seen]


class SubcommandRunner:
    def __init__(
        self,
        config: SolveigConfig,
        conversation: Conversation,
        provider_ref: ProviderRef,
        session_manager: SessionManager | None = None,
    ):
        self.config = config
        self.conversation = conversation
        self.provider_ref = provider_ref
        self.session_manager = session_manager

        # Flat lookup (every command + alias -> sub) drives dispatch; the ordered
        # list (unique subs in registration order) drives /help.
        self._registry: dict[str, Subcommand] = {}
        self._subcommands: list[Subcommand] = []

        self._discover_builtins()
        self._register_tool_subcommands()

    # ------------------------------------------------------------------
    # Registration / discovery
    # ------------------------------------------------------------------

    def _register(self, sub: Subcommand) -> None:
        """Append to the ordered list and map each of the subcommand's commands
        (canonical + aliases) into the flat lookup."""
        self._subcommands.append(sub)
        for command in sub.commands:
            self._registry[command] = sub

    def _discover_builtins(self) -> None:
        """Build a `Subcommand` for every `@subcommand`-marked method. `vars(cls)`
        preserves definition order, so /help lists built-ins in source order within
        each section — no sort hack, no hand-maintained registration block."""
        for name, function in vars(type(self)).items():
            mark = getattr(function, "_subcommand", None)
            if mark is None:
                continue
            bound = getattr(self, name)
            desc = mark.description or ((bound.__doc__ or "").strip().splitlines()[0])
            self._register(
                Subcommand(
                    commands=mark.commands,
                    handler=self._make_builtin_handler(bound, mark.commands[0]),
                    description=desc if desc else "",
                    usage=usage_of(bound),
                    section=mark.section,
                    is_detail=mark.is_detail,
                )
            )

    def _make_builtin_handler(self, bound: Callable, name: str) -> Callable:
        """Wrap a built-in method so it binds the raw tokens to its own signature
        (`bind_tokens`), showing a signature-derived usage line on a bad arg count."""

        async def handler(interface: SolveigInterface, *tokens: str) -> None:
            try:
                args = bind_tokens(bound, tokens)
            except UsageError:
                await interface.display_error(
                    f"Usage: {name} {usage_of(bound)}".rstrip()
                )
                return
            await bound(interface, *args)

        return handler

    def _register_tool_subcommands(self) -> None:
        """Register a `/tool` subcommand for every tool (core or plugin) that
        declares a `subcommand` ClassVar. Plugins are already initialized by the
        time the runner is built, so this init-time scan covers them too.

        The tool's class-level `Subcommand` is a shared template (description/usage
        filled by `BaseTool.__pydantic_init_subclass__`); it's *copied* per runner
        with the handler + `section="tools"` + `tool_name` so binding doesn't mutate
        the shared object. `tool_name` lets /help mark a disabled tool `(disabled)`.
        """
        for cls in tool_classes().values():
            template = cls.subcommand
            if not isinstance(template, Subcommand):
                continue
            sub = dataclasses.replace(
                template,
                handler=self._make_tool_handler(cls, template),
                section="tools",
                tool_name=cls.tool_name(),
            )
            self._register(sub)

    def _make_tool_handler(self, cls: type[BaseTool], template: Subcommand) -> Callable:
        """Build the handler that parses a `/tool` line into an instance and runs
        it through the shared group+hooks orchestration. `-h/--help` is intercepted
        upstream in `Subcommand.__call__`, so it never reaches argparse here."""

        async def handler(interface: SolveigInterface, *tokens: str) -> None:
            try:
                instance = cls.from_cli_tokens(list(tokens))
            except (SettingsError, ValidationError) as e:
                await interface.display_error(str(e))
                await interface.display_info(f"Usage: {template.help_line()}")
                return

            try:
                await run_tool_and_hooks(instance, self.config, interface)
            except (PluginException, ToolDisabledError) as e:
                # ToolDisabledError: refused uniformly for every tool by the
                # run_tool_and_hooks guard, so no per-tool check here.
                await interface.display_error(str(e))

        return handler

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

        # Longest-prefix match: try 2-token key first ("/config set"), then 1-token.
        for n in (2, 1):
            key = " ".join(tokens[:n])
            if key in self._registry:
                await self._registry[key](*tokens[n:], interface=interface)
                return True

        return False

    # ------------------------------------------------------------------
    # /config subcommands
    # ------------------------------------------------------------------

    @subcommand("/config", "/config list", section="config")
    async def config_list(self, interface: SolveigInterface) -> None:
        """List editable config fields with their current values."""
        lines = []
        for field_name, _description in editable_fields(self.config).items():
            value = get_config_value(self.config, field_name)
            display = self._format_field_value(value)
            lines.append(f"{field_name:<32} = {display}")
        await interface.display_text_box(
            "\n".join(lines), title="Config (editable fields)"
        )

    @subcommand("/config get", section="config", detail=True)
    async def config_get(self, interface: SolveigInterface, field: str) -> None:
        """Show current value for a field."""
        field_name = field.strip()
        fields = editable_fields(self.config)
        if field_name not in fields:
            await interface.display_error(
                f"Unknown field: '{field_name}'. Use /config list to see all fields."
            )
            return
        value = get_config_value(self.config, field_name)
        display = self._format_field_value(value)
        await interface.display_info(
            f"{field_name} = {display}  ({fields[field_name]})"
        )

    @subcommand("/config set", section="config", detail=True)
    async def config_set(
        self, interface: SolveigInterface, field: str, *value: str
    ) -> None:
        """Set a field (prompts if the value is omitted).

        Accepts `/config set <field> <value...>`, `/config set <field>=<value>`,
        or `/config set <field>` to be prompted. The value is the greedy rest of
        the line, so it may contain spaces.
        """
        field_name = field.strip()
        # inline `<field>=<value>` form
        if "=" in field_name and not value:
            field_name, _, inline = field_name.partition("=")
            field_name = field_name.strip()
            value = (inline,) if inline else ()

        if field_name not in editable_fields(self.config):
            await interface.display_error(
                f"Unknown or non-editable field: '{field_name}'. "
                "Use /config list to see all options."
            )
            return

        if not value:
            await self.edit_config_field(interface, field_name)
            return

        try:
            new_value = parse_config_value(self.config, field_name, " ".join(value))
        except (ValueError, KeyError) as e:
            await interface.display_error(f"Invalid value for '{field_name}': {e}")
            return

        await self._apply_and_confirm(field_name, new_value, interface)

    @subcommand("/config save", section="config", detail=True)
    async def config_save(self, interface: SolveigInterface, path: str = "") -> None:
        """Save changed fields to a config file.

        No-arg target = the highest-precedence loaded config file, else the
        default path. Writing just config._declared (not a full dump) keeps the
        saved file minimal — only what the user actually set.
        """
        target = path or (self.config.config_files or DEFAULT_CONFIG_PATHS)[0]
        try:
            sources.save_config(self.config.declared_config(), target)
        except OSError as e:
            await interface.display_error(f"Could not save config: {e}")
            return
        await interface.display_success(f"Config saved to {target}")

    async def edit_config_field(
        self, interface: SolveigInterface, field_name: str
    ) -> None:
        """Interactively prompt for a config field's new value and apply it.

        The interface's `on_edit_config_field` callback (stats-bar
        click-to-edit) and the prompt-on-omit path of `/config set` /
        `/model set`. Param order follows the producer-callback convention
        (interface first) so it can be wired directly.
        """
        if field_name not in editable_fields(self.config):
            await interface.display_error(
                f"Unknown or non-editable field: '{field_name}'. "
                "Use /config list to see all options."
            )
            return
        try:
            new_value = await prompt_for_field(field_name, self.config, interface)
        except (ValueError, KeyError) as e:
            await interface.display_error(f"Invalid value for '{field_name}': {e}")
            return
        await self._apply_and_confirm(field_name, new_value, interface)

    async def _apply_and_confirm(
        self, field_name: str, new_value: object, interface: SolveigInterface
    ) -> None:
        old_value = get_config_value(self.config, field_name)
        changed = await self.config.change_field(field_name, new_value)
        if not changed:
            await interface.display_info(f"config.{field_name} unchanged")
            return
        old_display = self._format_field_value(old_value)
        new_display = self._format_field_value(new_value)
        await interface.display_success(
            f"Changed config.{field_name}: {old_display} → {new_display}"
        )

    @staticmethod
    def _format_field_value(value: object) -> str:
        """Format a config value for display, driven entirely by the value's
        type — never by field name. Field-specific presentation lives on the
        field's type (SecretStr masks itself, ByteSize renders human-readable)."""
        if isinstance(value, SecretStr):
            return "***" if value.get_secret_value() else "(not set)"
        if isinstance(value, ByteSize):
            return value.human_readable()
        if isinstance(value, re.Pattern):
            return value.pattern
        if isinstance(value, list):
            return (
                ", ".join(SubcommandRunner._format_field_value(v) for v in value)
                if value
                else "(empty)"
            )
        if hasattr(value, "name"):  # Palette, APIType subclass
            return value.name
        return repr(value)

    # ------------------------------------------------------------------
    # /model subcommands
    # ------------------------------------------------------------------

    @subcommand("/model", "/model info", section="model")
    async def model_info(self, interface: SolveigInterface) -> None:
        """Show current model details."""
        if not self.config.api.model:
            await interface.display_warning(
                "No model configured. Use /model set <name>."
            )
            return
        info = self.provider_ref.model_info
        lines = [f"Model: {self.config.api.model}"]
        if info:
            if info.context_length is not None:
                lines.append(f"Context length: {info.context_length:,} tokens")
            if info.input_price is not None:
                lines.append(f"Input price:  ${info.input_price}/M tokens")
            if info.output_price is not None:
                lines.append(f"Output price: ${info.output_price}/M tokens")
        else:
            lines.append("(No details cached — try /model refresh)")
        await interface.display_text_box("\n".join(lines), title="Model Info")

    @subcommand("/model set", section="model", detail=True)
    async def model_set(self, interface: SolveigInterface, name: str = "") -> None:
        """Change the model (prompts if the name is omitted)."""
        if name:
            await self._apply_and_confirm("api.model", name, interface)
        else:
            await self.edit_config_field(interface, "api.model")

    @subcommand("/model refresh", section="model", detail=True)
    async def model_refresh(self, interface: SolveigInterface) -> None:
        """Re-fetch model info from the API."""
        if not self.config.api.model:
            await interface.display_error("No model configured to refresh.")
            return
        self.provider_ref.model_info = None
        await fetch_and_apply_model_info(self.config, self.provider_ref, interface)

    @subcommand("/model list", section="model", detail=True)
    async def model_list(self, interface: SolveigInterface) -> None:
        """List available models from the API."""
        try:
            async with interface.with_cancellable(
                self.config.api.type.list_models(self.provider_ref.provider),
                status="Fetching model list",
            ) as task:
                names = await task
        except NotImplementedError:
            await interface.display_error(
                "This API type does not support listing models."
            )
            return
        except Exception as e:
            await interface.display_error(f"Could not list models: {e}")
            return
        await interface.display_text_box(
            "\n".join(f"• {n}" for n in names),
            title=f"Available Models ({len(names)})",
        )

    # ------------------------------------------------------------------
    # Basic subcommands
    # ------------------------------------------------------------------

    @subcommand("/help", section="basic")
    async def help(self, interface: SolveigInterface) -> str:
        """Print this message."""
        help_str = f"""
You're using Solveig to interact with an AI assistant at {self.config.api.url}.
This message was printed because you used the '/help' sub-command.
You can exit Solveig by pressing Ctrl+C or sending '/exit'.
""".strip()

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
        # Marks a tool subcommand (disabled) in /help when its tool is off.
        return sub.tool_name is not None and not self.config.is_tool_enabled(
            sub.tool_name
        )

    @subcommand("/exit", section="basic")
    async def exit(self, interface: SolveigInterface) -> None:
        """Exit the application (Ctrl+C also works)."""
        await interface.stop()

    # ------------------------------------------------------------------
    # /mcp subcommands
    # ------------------------------------------------------------------

    @subcommand("/mcp", "/mcp list", section="mcp")
    async def mcp_list(self, interface: SolveigInterface) -> None:
        """List connected MCP servers."""
        if not MCP_CONNECTIONS:
            await interface.display_info("No MCP servers connected.")
            return
        lines = []
        for conn in MCP_CONNECTIONS.values():
            lines.append(
                f"**{conn.display_name}** ({conn.url}) — "
                f"{len(conn.tool_names)} tools: {', '.join(conn.tool_names)}"
            )
        await interface.display_text_box("\n".join(lines), title="MCP Connections")

    @subcommand("/mcp connect", section="mcp", detail=True)
    async def mcp_connect(self, interface: SolveigInterface, url: str) -> None:
        """Connect to an MCP server."""
        # connect() returns None (and displays its own error) on failure — it
        # doesn't raise, so there's nothing to catch here.
        await connect(MCPServerConfig(url=url), self.config, interface)

    @subcommand("/mcp disconnect", section="mcp", detail=True)
    async def mcp_disconnect(self, interface: SolveigInterface, name: str) -> None:
        """Disconnect from an MCP server."""
        conn = find_connection(name)
        if conn is None:
            await interface.display_error(
                f"No connection matching '{name}'. "
                "Use /mcp list to see active connections."
            )
            return
        await disconnect(conn.url, self.config, interface)
        await interface.display_success(f"Disconnected from '{conn.display_name}'.")

    # ------------------------------------------------------------------
    # /session commands
    # ------------------------------------------------------------------

    @subcommand(
        "/session", "/session list", "/sessions", "/sessions list", section="session"
    )
    async def session_list(self, interface: SolveigInterface) -> None:
        """List stored sessions."""
        if self.session_manager is None:
            await interface.display_error(
                "Session manager is disabled (auto_save_session=false and no --resume)"
            )
            return
        sessions = await self.session_manager.list_sessions()
        if not sessions:
            await interface.display_text("No stored sessions.")
            return
        lines = []
        for i, session_data in enumerate(sessions, 1):
            age = format_age(session_data["_mtime"])
            message_count = session_data.get("message_count", 0)
            tokens = session_data.get("total_tokens_sent", 0) + session_data.get(
                "total_tokens_received", 0
            )
            lines.append(
                f"{i}. **{session_data['id']}** — {age}, "
                f"{message_count} messages, {tokens} tokens."
            )
        await interface.display_text_box(
            "\n".join(lines), language="markdown", title="Sessions"
        )

    @subcommand(
        "/session store", "/sessions store", "/store", section="session", detail=True
    )
    async def session_store(self, interface: SolveigInterface, name: str = "") -> None:
        """Store current session."""
        if self.session_manager is None:
            await interface.display_error(
                "Session manager is disabled (auto_save_session=false and no --resume)"
            )
            return
        filename = await self.session_manager.store(self.conversation, name or None)
        await interface.display_success(f"Session stored: {filename}")

    @subcommand("/session delete", "/sessions delete", section="session", detail=True)
    async def session_delete(self, interface: SolveigInterface, name: str) -> None:
        """Delete a session."""
        if self.session_manager is None:
            await interface.display_error(
                "Session manager is disabled (auto_save_session=false and no --resume)"
            )
            return
        try:
            path_str = await self.session_manager.resolve(name)
        except FileNotFoundError as e:
            await interface.display_error(str(e))
            return
        filename = os.path.basename(path_str)
        choice = await interface.ask_choice(
            f"Delete session '{filename}'?", ["Yes", "No"], add_cancel=False
        )
        if choice == 0:
            await self.session_manager.delete(name)
            await interface.display_success(f"Deleted {filename}")

    @subcommand(
        "/session resume", "/sessions resume", "/resume", section="session", detail=True
    )
    async def session_resume(self, interface: SolveigInterface, name: str = "") -> None:
        """Resume a session (latest if omitted)."""
        if self.session_manager is None:
            await interface.display_error(
                "Session manager is disabled (auto_save_session=false and no --resume). "
                "Restart with --resume or enable auto_save_session."
            )
            return
        try:
            session_data = await self.session_manager.load(name or None)
        except FileNotFoundError as e:
            await interface.display_error(str(e))
            return
        await self.session_manager.announce_resumed_session(session_data, interface)
        await self.conversation.load(session_data["messages"], session_data["usage"])
        await interface.display_success("Session loaded. Continue your conversation.")
