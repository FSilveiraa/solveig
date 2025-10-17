import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from solveig.utils.file import Filesystem

if TYPE_CHECKING:
    from solveig import SolveigConfig
    from solveig.interface import SolveigInterface
    from solveig.schema.message import MessageHistory


class SubcommandRunner:
    def __init__(self, config: "SolveigConfig", message_history: "MessageHistory"):
        self.config = config
        self.message_history = message_history  # for logging chats
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
        }

    async def __call__(self, subcommand: str, interface: "SolveigInterface"):
        # ok this looks pretty cool
        subcommand, *args = subcommand.split(" ")
        try:
            call = self.subcommands_map[subcommand][0]
        except KeyError:
            return False
        else:
            if asyncio.iscoroutinefunction(call):
                await call(interface, *args)
            else:
                call(interface, *args)
        return True

    async def draw_help(self, interface: "SolveigInterface", *args, **kwargs) -> str:
        help_str = f"""
You're using Solveig to interact with an AI assistant at {self.config.url}.
This message was printed because you used the '/help' sub-command.
You can exit Solveig by pressing Ctrl+C or sending '/exit'.
You have the following sub-commands available:
""".strip()
        for _, (_, description) in self.subcommands_map.items():
            help_str += f"\n  • {description}"
        await interface.display_text_block(help_str, title="Help")
        return help_str

    async def stop_interface(self, interface: "SolveigInterface", *args, **kwargs):
        await interface.stop()

    async def log_conversation(
        self, interface: "SolveigInterface", path, *args, **kwargs
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
                    f"{"Updating" if already_exists else "Creating"} {abs_path} since it matches config.auto_allowed_paths"
                )
            else:
                question = f"Allow {"updating" if already_exists else "creating"} file?"
                if not await interface.ask_yes_no(question):
                    return

            try:
                await Filesystem.write_file(abs_path, content)
                await interface.display_success("Log exported")
            except Exception as e:
                await interface.display_error(f"Found error when writing file: {e}")
