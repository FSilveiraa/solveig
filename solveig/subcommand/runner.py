"""SubcommandRunner — dispatches user-typed /commands to registered handlers."""

from __future__ import annotations

import dataclasses
import shlex
import typing
from collections.abc import Callable

from solveig.config import SolveigConfig
from solveig.config.editor import (
    CONFIG_EDITABLE_FIELDS,
    _parse_field_value,
    _unwrap_optional,
    apply_config_field,
    fetch_and_apply_model_info,
    prompt_for_field,
)
from solveig.interface import SolveigInterface
from solveig.llm import ClientRef
from solveig.schema.dynamic import get_tools_union
from solveig.schema.message import MessageHistory
from solveig.schema.tool import CORE_TOOLS
from solveig.schema.tool.base import BaseTool
from solveig.sessions.manager import SessionManager
from solveig.subcommand.base import Subcommand
from solveig.utils.misc import convert_size_to_human_readable, format_age


class SubcommandRunner:
    def __init__(
        self,
        config: SolveigConfig,
        message_history: MessageHistory,
        client_ref: ClientRef,
        session_manager: SessionManager | None = None,
    ):
        self.config = config
        self.message_history = message_history
        self.client_ref = client_ref
        self.session_manager = session_manager

        # Sectioned registries — used by draw_help for structured output
        self._basic: dict[str, Subcommand] = {}
        self._config: dict[str, Subcommand] = {}
        self._model: dict[str, Subcommand] = {}
        self._session: dict[str, Subcommand] = {}
        self._tools: dict[str, Subcommand] = {}  # core tool subcommands
        self._plugins: dict[str, Subcommand] = {}  # plugin tool subcommands

        # Flat registry for O(1) lookup in __call__
        self._registry: dict[str, Subcommand] = {}

        self._register_builtins()
        self._register_tool_subcommands()

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------

    def _reg(self, section: dict[str, Subcommand], sub: Subcommand) -> Subcommand:
        """Register *sub* in *section* and the flat lookup.

        All commands in ``sub.commands`` are added to the flat registry;
        only the first (canonical) command is added to the section dict.
        """
        primary = sub.commands[0]
        section[primary] = sub
        self._registry[primary] = sub
        for alias in sub.commands[1:]:
            self._registry[alias] = sub
        return sub

    def _reg_alias(self, name: str, source: Subcommand) -> None:
        """Register an alias in the flat lookup only (never shown in /help)."""
        self._registry[name] = source

    def _sub(
        self,
        commands: str | list[str],
        handler: Callable,
        description: str = "",
        usage: str = "",
        is_detail: bool = False,
    ) -> Subcommand:
        """Convenience factory for built-in Subcommand instances."""
        if isinstance(commands, str):
            commands = [commands]
        return Subcommand(
            commands=commands,
            handler=handler,
            description=description,
            usage=usage,
            is_detail=is_detail,
        )

    def _register_builtins(self) -> None:
        r, s = self._reg, self._sub

        # Basic
        r(self._basic, s("/help", self.draw_help, "Print this message"))
        r(
            self._basic,
            s("/exit", self.stop_interface, "Exit the application (Ctrl+C also works)"),
        )
        r(
            self._basic,
            s("/store", self.session_store, "Store current session", usage="[name]"),
        )
        r(
            self._basic,
            s(
                "/resume",
                self.session_resume,
                "Resume a session",
                usage="[name or path]",
            ),
        )

        # Config
        r(
            self._config,
            s("/config", self._config_list_cmd, "List editable config fields"),
        )
        r(
            self._config,
            s(
                "/config list",
                self._config_list_cmd,
                "Show all fields with current values",
                is_detail=True,
            ),
        )
        r(
            self._config,
            s(
                "/config get",
                self._config_get_cmd,
                "Show current value for a field",
                usage="<field>",
                is_detail=True,
            ),
        )
        r(
            self._config,
            s(
                "/config set",
                self._config_set_cmd,
                "Set a field (prompts if omitted)",
                usage="<field> [value]",
                is_detail=True,
            ),
        )

        # Model
        r(self._model, s("/model", self._model_info, "Show current model details"))
        r(
            self._model,
            s(
                "/model info",
                self._model_info,
                "Show current model details",
                is_detail=True,
            ),
        )
        r(
            self._model,
            s(
                "/model set",
                self._model_set_cmd,
                "Change the model",
                usage="[name]",
                is_detail=True,
            ),
        )
        r(
            self._model,
            s(
                "/model refresh",
                self._model_refresh,
                "Re-fetch model info from API",
                is_detail=True,
            ),
        )
        r(
            self._model,
            s(
                "/model list",
                self._model_list,
                "List available models from API",
                is_detail=True,
            ),
        )

        # Session — /sessions is a dispatch-only alias block
        r(self._session, s("/session", self.session_list, "Manage stored sessions"))
        r(
            self._session,
            s(
                "/session list",
                self.session_list,
                "List stored sessions",
                is_detail=True,
            ),
        )
        r(
            self._session,
            s(
                "/session store",
                self.session_store,
                "Store current session",
                usage="[name]",
                is_detail=True,
            ),
        )
        r(
            self._session,
            s(
                "/session delete",
                self.session_delete,
                "Delete a session",
                usage="<name or path>",
                is_detail=True,
            ),
        )
        r(
            self._session,
            s(
                "/session resume",
                self.session_resume,
                "Resume a session (latest if omitted)",
                usage="[name or path]",
                is_detail=True,
            ),
        )
        for sub in ("", " list", " store", " delete", " resume"):
            self._reg_alias(f"/sessions{sub}", self._registry[f"/session{sub}"])

    def _register_tool_subcommands(self) -> None:
        for tool_cls in typing.get_args(get_tools_union()):
            template: Subcommand | None = getattr(tool_cls, "subcommand", None)
            if not isinstance(template, Subcommand):
                continue
            section = self._tools if tool_cls in CORE_TOOLS else self._plugins
            handler = self._make_tool_handler(tool_cls)
            registered = dataclasses.replace(template, handler=handler)
            self._reg(section, registered)

    def _make_tool_handler(self, tool_cls: type[BaseTool]) -> Callable:
        async def handler(
            interface: SolveigInterface, *args: str, **kwargs: str
        ) -> None:
            try:
                tool = tool_cls.from_cli_args(*args, **kwargs)
            except Exception as e:
                title = tool_cls.model_fields["title"].default
                await interface.display_error(f"Invalid arguments for /{title}: {e}")
                return
            result = await tool.solve(config=self.config, interface=interface)
            if result:
                await self.message_history.add_result(result)

        return handler

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def __call__(self, subcommand: str, interface: SolveigInterface) -> bool:
        try:
            tokens = shlex.split(subcommand)
        except ValueError:
            tokens = subcommand.split()
        if not tokens:
            return False

        # Longest-prefix match: try 2-token key first ("/config set"), then 1-token
        for n in (2, 1):
            key = " ".join(tokens[:n])
            if key in self._registry:
                sub = self._registry[key]
                remaining = tokens[n:]
                await sub(*remaining, interface=interface)
                return True

        return False

    # ------------------------------------------------------------------
    # /config subcommands
    # ------------------------------------------------------------------

    async def _config_list_cmd(self, interface: SolveigInterface, *args) -> None:
        """List all editable config fields with their current values."""
        lines = []
        for field_name, _description in CONFIG_EDITABLE_FIELDS.items():
            value = getattr(self.config, field_name)
            display = self._format_field_value(field_name, value)
            lines.append(f"{field_name:<26} = {display}")
        await interface.display_text_block(
            "\n".join(lines), title="Config (editable fields)"
        )

    async def _config_get_cmd(self, interface: SolveigInterface, *args) -> None:
        """Show current value and description for a single field."""
        if not args:
            await interface.display_error("Usage: /config get <field>")
            return
        field_name = args[0].strip()
        if field_name not in CONFIG_EDITABLE_FIELDS:
            await interface.display_error(
                f"Unknown field: '{field_name}'. Use /config list to see all fields."
            )
            return
        value = getattr(self.config, field_name)
        display = self._format_field_value(field_name, value)
        description = CONFIG_EDITABLE_FIELDS[field_name]
        await interface.display_info(f"{field_name} = {display}  ({description})")

    async def _config_set_cmd(
        self, interface: SolveigInterface, *args, **kwargs
    ) -> None:
        """
        Set a config field. Supports:
          /config set <key> <value>
          /config set <key>           (prompts for value)
          /config set <key>=<value>
        """
        # _parse_cli_args turns "api_key=val" into kwargs; reconstruct as positional token
        if not args and kwargs:
            args = tuple(f"{k}={v}" for k, v in kwargs.items())

        if not args:
            await interface.display_error(
                "Usage: /config set <field> [value]  or  /config set <field>=<value>"
            )
            return

        # Parse key=value or "key value" forms
        if "=" in args[0]:
            field_name, _, value_str = args[0].partition("=")
            value_str = value_str if value_str else None
        else:
            field_name = args[0]
            value_str = " ".join(args[1:]) if len(args) > 1 else None

        field_name = field_name.strip()
        if field_name not in CONFIG_EDITABLE_FIELDS:
            await interface.display_error(
                f"Unknown or non-editable field: '{field_name}'. "
                "Use /config list to see all options."
            )
            return

        try:
            if value_str is not None:
                hints = typing.get_type_hints(self.config.__class__)
                raw_type = _unwrap_optional(hints[field_name])
                new_value = _parse_field_value(field_name, raw_type, value_str)
            else:
                new_value = await prompt_for_field(field_name, self.config, interface)
        except (ValueError, KeyError) as e:
            await interface.display_error(f"Invalid value for '{field_name}': {e}")
            return

        old_value = getattr(self.config, field_name)
        await apply_config_field(
            field_name,
            new_value,
            self.config,
            self.client_ref,
            interface,
            self.message_history,
        )
        old_display = self._format_field_value(field_name, old_value)
        new_display = self._format_field_value(field_name, new_value)
        await interface.display_success(
            f"Changed config.{field_name}: {old_display} → {new_display}"
        )

    @staticmethod
    def _format_field_value(field_name: str, value: object) -> str:
        """Format a config value for display."""
        if field_name == "api_key":
            return "***" if value else "(not set)"
        if field_name == "min_disk_space_left" and isinstance(value, int):
            return convert_size_to_human_readable(value)
        if field_name in ("auto_allowed_paths", "auto_execute_commands") and isinstance(
            value, list
        ):
            return ", ".join(str(v) for v in value) if value else "(empty)"
        if hasattr(value, "name"):  # Palette, APIType subclass
            return value.name
        return repr(value)

    # ------------------------------------------------------------------
    # /model subcommands
    # ------------------------------------------------------------------

    async def _model_set_cmd(self, interface: SolveigInterface, *args) -> None:
        await self._config_set_cmd(interface, "model", *args)

    async def _model_info(self, interface: SolveigInterface, *args) -> None:
        if not self.config.model:
            await interface.display_warning(
                "No model configured. Use /model set <name>."
            )
            return
        info = self.config.model_info
        lines = [f"Model: {self.config.model}"]
        if info:
            if info.context_length is not None:
                lines.append(f"Context length: {info.context_length:,} tokens")
            if info.input_price is not None:
                lines.append(f"Input price:  ${info.input_price}/M tokens")
            if info.output_price is not None:
                lines.append(f"Output price: ${info.output_price}/M tokens")
        else:
            lines.append("(No details cached — try /model refresh)")
        await interface.display_text_block("\n".join(lines), title="Model Info")

    async def _model_refresh(self, interface: SolveigInterface, *args) -> None:
        if not self.config.model:
            await interface.display_error("No model configured to refresh.")
            return
        self.config.model_info = None
        await fetch_and_apply_model_info(
            self.config, self.client_ref, interface, self.message_history
        )

    async def _model_list(self, interface: SolveigInterface, *args) -> None:
        raw_client = getattr(self.client_ref.client, "client", None)
        if raw_client is None:
            await interface.display_error(
                "This API type does not support listing models."
            )
            return
        try:
            async with interface.with_animation("Fetching model list...", "Ready"):
                models = await raw_client.models.list()
            names = sorted(m.id for m in models.data)
            await interface.display_text_block(
                "\n".join(f"• {n}" for n in names),
                title=f"Available Models ({len(names)})",
            )
        except Exception as e:
            await interface.display_error(f"Could not list models: {e}")

    # ------------------------------------------------------------------
    # Basic subcommands
    # ------------------------------------------------------------------

    async def draw_help(self, interface: SolveigInterface, *args, **kwargs) -> str:
        help_str = f"""
You're using Solveig to interact with an AI assistant at {self.config.url}.
This message was printed because you used the '/help' sub-command.
You can exit Solveig by pressing Ctrl+C or sending '/exit'.
""".strip()

        sections = [
            ("Basic sub-commands", self._basic),
            ("Config sub-commands", self._config),
            ("Model sub-commands", self._model),
            ("Session sub-commands", self._session),
            ("Tool sub-commands", self._tools),
            ("Plugin tools", self._plugins),
        ]
        for section_title, registry in sections:
            top = [(cmd, e) for cmd, e in registry.items() if not e.is_detail]
            details = [(cmd, e) for cmd, e in registry.items() if e.is_detail]
            if not top and not details:
                continue
            help_str += f"\n\n{section_title}:"
            for _cmd, sub in top:
                help_str += f"\n  • {sub.help_line()}"
            for _cmd, sub in details:
                help_str += f"\n      {sub.help_line()}"

        await interface.display_text_block(help_str, title="Help")
        return help_str

    async def stop_interface(self, interface: SolveigInterface, *args, **kwargs):
        await interface.stop()

    # ------------------------------------------------------------------
    # /session commands
    # ------------------------------------------------------------------

    async def session_list(self, interface: SolveigInterface, *args, **kwargs):
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
        for i, s in enumerate(sessions, 1):
            age = format_age(s["_mtime"])
            count = s.get("metadata", {}).get("message_count", "?")
            lines.append(f"{i}. **{s['id']}** — {age}, {count} messages")
        await interface.display_text_block("\n".join(lines), title="Sessions")

    async def session_store(self, interface: SolveigInterface, *args, **kwargs):
        if self.session_manager is None:
            await interface.display_error(
                "Session manager is disabled (auto_save_session=false and no --resume)"
            )
            return
        name = args[0] if args else None
        filename = await self.session_manager.store(self.message_history, name)
        await interface.display_success(f"Session stored: {filename}")

    async def session_delete(self, interface: SolveigInterface, *args, **kwargs):
        if self.session_manager is None:
            await interface.display_error(
                "Session manager is disabled (auto_save_session=false and no --resume)"
            )
            return
        if not args:
            await interface.display_error("Usage: /session delete <name>")
            return
        name = args[0]
        try:
            path_str = await self.session_manager._fuzzy_find(name)
        except FileNotFoundError as e:
            await interface.display_error(str(e))
            return
        filename = path_str.rsplit("/", 1)[-1]
        choice = await interface.ask_choice(
            f"Delete session '{filename}'?", ["Yes", "No"], add_cancel=False
        )
        if choice == 0:
            await self.session_manager.delete(name)
            await interface.display_success(f"Deleted {filename}")

    async def session_resume(self, interface: SolveigInterface, *args, **kwargs):
        if self.session_manager is None:
            await interface.display_error(
                "Session manager is disabled (auto_save_session=false and no --resume). "
                "Restart with --resume or enable auto_save_session."
            )
            return
        name = args[0] if args else None
        try:
            session_data = await self.session_manager.load(name)
        except FileNotFoundError as e:
            await interface.display_error(str(e))
            return
        self.message_history.load_messages(
            self.session_manager.reconstruct_messages(session_data)
        )
        await self.session_manager.display_loaded_session(
            session_data, self.message_history, interface
        )
        await interface.display_success("Session loaded. Continue your conversation.")
