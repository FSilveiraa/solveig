import asyncio

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from solveig import SolveigConfig
    from solveig.interface import SolveigInterface
    from solveig.schema.message import MessageHistory


class SubcommandRunner:
    def __init__(self, config: "SolveigConfig", message_history: "MessageHistory"):
        self.config = config
        self.message_history = message_history # for logging chats
        self.subcommands_map = {
            "/help": (self.draw_help, "Print this message"),
            "/exit": (self.stop_interface, "Exit the application"),
            # "/log <path>": (log_conversation, "Log the conversation to <path>"),
        }

    async def __call__(self, subcommand: str, interface: "SolveigInterface", *args, **kwargs):
        call = self.subcommands_map[subcommand][0]
        if asyncio.iscoroutinefunction(call):
            return await call(interface, *args, **kwargs)
        else:
            return call(interface, *args, **kwargs)

    async def draw_help(self, interface: "SolveigInterface", *args, **kwargs) -> str:
        help_str = f"""
You're using Solveig to interact with an AI assistant at {self.config.url}.
This message was printed because you used the '/help' sub-command.
You can exit Solveig by pressing Ctrl+C or sending '/exit'.
You have the following sub-commands available:
""".strip()
        for subcommand, (_, description) in self.subcommands_map.items():
            help_str += f"\n  • {subcommand}: {description}"
        await interface.display_text_block(help_str, title="Help")
        return help_str

    async def stop_interface(self, interface: "SolveigInterface", *args, **kwargs):
        await interface.stop()

    async def log_conversation(self, interface, *args, **kwargs):
        pass
