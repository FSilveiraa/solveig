import asyncio
import typing
from collections.abc import Callable

from solveig.config import SolveigConfig
from solveig.config_editor import (
    CONFIG_EDITABLE_FIELDS,
    _parse_field_value,
    _unwrap_optional,
    apply_config_field,
    fetch_and_apply_model_info,
    prompt_for_field,
)
from solveig.interface import SolveigInterface
from solveig.llm import ClientRef
from solveig.schema.message import MessageHistory
from solveig.sessions.manager import SessionManager
from solveig.utils.file import Filesystem
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
        self.subcommands_map: dict[str, tuple[Callable, str]] = {
            "/help": (self.draw_help, "/help: Print this message"),
            "/exit": (
                self.stop_interface,
                "/exit: Exit the application (Ctrl+C also works)",
            ),
            "/log": (
                self.log_conversation,
                "/log <path>: Log the conversation to <path>",
            ),
            "/store": (
                self.session_store,
                "/store [name]: Store current session (shorthand for /session store)",
            ),
            "/resume": (
                self.session_resume,
                "/resume [name]: Resume a session (shorthand for /session resume)",
            ),
        }

    async def __call__(self, subcommand: str, interface: SolveigInterface):
        parts = subcommand.split()
        if not parts:
            return False
        cmd = parts[0]
        args = parts[1:]

        # Exact-match single-word commands
        if cmd in self.subcommands_map:
            call, _ = self.subcommands_map[cmd]
            if asyncio.iscoroutinefunction(call):
                await call(interface, *args)
            else:
                call(interface, *args)
            return True

        # Multi-word prefix commands
        if cmd == "/model":
            await self._model_cmd(interface, *args)
            return True

        if cmd == "/config":
            sub = args[0] if args else "list"
            sub_args = args[1:]
            dispatch = {
                "list": self._config_list_cmd,
                "get": self._config_get_cmd,
                "set": self._config_set_cmd,
            }
            handler = dispatch.get(sub)
            if handler is None:
                await interface.display_error(
                    f"Unknown /config sub-command: '{sub}'. Use: list, get, set"
                )
                return True
            await handler(interface, *sub_args)
            return True

        if cmd in ("/session", "/sessions"):
            sub = args[0] if args else "list"
            sub_args = args[1:]
            dispatch = {
                "list": self.session_list,
                "store": self.session_store,
                "delete": self.session_delete,
                "resume": self.session_resume,
            }
            handler = dispatch.get(sub)
            if handler is None:
                await interface.display_error(
                    f"Unknown /session sub-command: '{sub}'. Use: list, store, delete, resume"
                )
                return True
            await handler(interface, *sub_args)
            return True

        if cmd == "/store":
            await self.session_store(interface, *args)
            return True

        if cmd == "/resume":
            await self.session_resume(interface, *args)
            return True

        return False

    # ------------------------------------------------------------------
    # /config subcommands
    # ------------------------------------------------------------------

    async def _config_list_cmd(self, interface: SolveigInterface, *args):
        """List all editable config fields with their current values."""
        lines = []
        for field_name, _description in CONFIG_EDITABLE_FIELDS.items():
            value = getattr(self.config, field_name)
            display = self._format_field_value(field_name, value)
            lines.append(f"{field_name:<26} = {display}")
        await interface.display_text_block(
            "\n".join(lines), title="Config (editable fields)"
        )

    async def _config_get_cmd(self, interface: SolveigInterface, *args):
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

    async def _config_set_cmd(self, interface: SolveigInterface, *args):
        """
        Set a config field. Supports:
          /config set <key> <value>
          /config set <key>           (prompts for value)
          /config set <key>=<value>
        """
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
                # Value provided inline — parse without prompting
                hints = typing.get_type_hints(self.config.__class__)
                raw_type = _unwrap_optional(hints[field_name])
                new_value = _parse_field_value(field_name, raw_type, value_str)
            else:
                # No value — use type-aware UI to prompt
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

    async def _model_cmd(self, interface: SolveigInterface, *args):
        sub = args[0] if args else "info"
        sub_args = args[1:]

        if sub == "info":
            await self._model_info(interface)
        elif sub == "set":
            # Delegate entirely to /config set model [name]
            await self._config_set_cmd(interface, "model", *sub_args)
        elif sub == "refresh":
            await self._model_refresh(interface)
        elif sub == "list":
            await self._model_list(interface)
        else:
            await interface.display_error(
                f"Unknown /model sub-command: '{sub}'. "
                "Use: info, set <name>, refresh, list"
            )

    async def _model_info(self, interface: SolveigInterface):
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

    async def _model_refresh(self, interface: SolveigInterface):
        if not self.config.model:
            await interface.display_error("No model configured to refresh.")
            return
        self.config.model_info = None
        await fetch_and_apply_model_info(
            self.config, self.client_ref, interface, self.message_history
        )

    async def _model_list(self, interface: SolveigInterface):
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
    # Original subcommands
    # ------------------------------------------------------------------

    async def draw_help(self, interface: SolveigInterface, *args, **kwargs) -> str:
        help_str = f"""
You're using Solveig to interact with an AI assistant at {self.config.url}.
This message was printed because you used the '/help' sub-command.
You can exit Solveig by pressing Ctrl+C or sending '/exit'.

Built-in sub-commands:
""".strip()
        for _, (_, description) in self.subcommands_map.items():
            help_str += f"\n  • {description}"
        help_str += """

Config sub-commands:
  • /config list                   — show all editable fields with current values
  • /config get <field>            — show current value for a field
  • /config set <field> [value]    — set a field (prompts if value omitted)
  • /config set <field>=<value>    — set a field inline

Model shortcuts (equivalent to /config set model …):
  • /model                         — show current model details
  • /model set [name]              — change model
  • /model refresh                 — re-fetch model info from API
  • /model list                    — list models available from API

Session sub-commands:
  • /session list                  — list stored sessions
  • /session store [name]          — store current session
  • /session delete <name>         — delete a session (fuzzy match)
  • /session resume [name]         — resume a session (latest if no name)
  • /store [name]                  — shorthand for /session store
  • /resume [name]                 — shorthand for /session resume"""
        await interface.display_text_block(help_str, title="Help")
        return help_str

    async def stop_interface(self, interface: SolveigInterface, *args, **kwargs):
        await interface.stop()

    async def log_conversation(
        self, interface: SolveigInterface, path, *args, **kwargs
    ):
        async with interface.with_group("Log"):
            content = self.message_history.to_example()
            if not content:
                await interface.display_warning(
                    "Cannot export conversation: no messages logged yet"
                )
                return

            await interface.display_file_info(
                source_path=path, is_directory=False, source_content=content
            )

            abs_path = Filesystem.get_absolute_path(path)
            already_exists = await Filesystem.exists(abs_path)
            auto_write = Filesystem.path_matches_patterns(
                abs_path, self.config.auto_allowed_paths
            )

            if auto_write:
                await interface.display_text(
                    f"{'Updating' if already_exists else 'Creating'} {abs_path} since it matches config.auto_allowed_paths"
                )
            else:
                if (
                    await interface.ask_choice(
                        f"Allow {'updating' if already_exists else 'creating'} file?",
                        choices=["Yes", "No"],
                    )
                    == 1
                ):
                    return

            try:
                await Filesystem.write_file(abs_path, content)
                await interface.display_success("Log exported")
            except Exception as e:
                await interface.display_error(f"Found error when writing file: {e}")

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
        self.message_history.load_session(session_data["messages"])
        await self.session_manager.display_loaded_session(session_data, interface)
        await interface.display_success("Session loaded. Continue your conversation.")
