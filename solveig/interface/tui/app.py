"""Main Textual application class."""

import asyncio
from typing import override

from textual import events
from textual.app import App as TextualApp
from textual.app import ComposeResult
from textual.binding import Binding
from textual.keys import format_key

from solveig.interface.base import SolveigInterface, Level
from solveig.interface.themes import THEMES
from solveig.pending.user_message_queue import UserMessageQueue
from solveig.utils.misc import copy_to_clipboard

from .chat import ChatArea
from .input import InputBar
from .pending import PendingMessages
from .stats import StatsBar
from ...config import SolveigConfig


# Level → (style, prefix emoji) mapping for the Textual frontend.
LEVEL_SYMBOLS: dict[Level, str] = {
    Level.WARNING: "⚠",
    Level.ERROR: "🗙",
}


class SolveigTextualApp(TextualApp):
    """
    Minimal TextualApp subclass with only essential Solveig customizations.
    """

    BINDINGS = [
        Binding("escape", "focus_input", "Back to input", show=False),
        Binding("escape", "cancel_tasks", "Cancel"),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(
        self,
        config: SolveigConfig,
        interface: SolveigInterface,
        user_message_queue: UserMessageQueue,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._config = config
        self._interface = interface
        self._user_message_queue = user_message_queue

        # Register every palette as a Textual theme and select the configured
        # one, so the widget CSS's $accent/$border/$group/... variables resolve and
        # switching themes at runtime is just `self.theme = name`.
        for theme in THEMES:
            self.register_theme(theme.to_textual_theme())

        # This is the actual theme name that Textual will use, not a TuiTheme
        self.theme = self._config.interface.tui.theme.name

        # Register an observer for the code value
        @self._config.on_change("interface.tui.theme")
        async def _on_theme_change(_config, paths):
            self.theme = _config.interface.tui.theme.name

        # Cached widget references (set in on_mount)
        self._chat: ChatArea
        self._input_bar: InputBar
        self._stats_bar: StatsBar
        self._queued_messages_display: PendingMessages

        # Readiness event
        self.is_ready = asyncio.Event()

    def compose(self) -> ComposeResult:
        """Create the main layout."""
        yield ChatArea()
        yield PendingMessages(self._user_message_queue)
        yield InputBar(self._user_message_queue)
        yield StatsBar(self._interface)

    def on_mount(self) -> None:
        """Called when the app is mounted and widgets are available."""
        # Cache widget references
        self._chat = self.query_one(ChatArea)
        self._input_bar = self.query_one(InputBar)
        self._stats_bar = self.query_one(StatsBar)
        self._queued_messages_display = self.query_one(PendingMessages)

        # Focus the input widget so user can start typing immediately
        self._input_bar.focus()

    def on_ready(self) -> None:
        # Announce interface is ready
        self.is_ready.set()

    @override
    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Textual method, checks whether an action can run in the current context."""
        if action == "focus_input":
            return not self._input_bar.has_focus_within
        elif action == "cancel_tasks":
            return bool(self._interface.get_active_tasks())
        return True

    def action_focus_input(self) -> None:
        self._input_bar.focus()

    def action_cancel_tasks(self) -> None:
        self._interface.cancel_task()

    def cancel_hint(self) -> str | None:
        """Builds the cancellation hint from the active bindings."""
        keys = [
            format_key(key)
            for key, active in self.active_bindings.items()
            if active.enabled and active.binding.action == "cancel_tasks"
        ]
        return f"({'/'.join(keys)} to cancel)" if keys else None

    async def on_mouse_up(self, event: events.MouseUp) -> None:
        """Intercept mouse-up to auto-copy a completed click-drag text selection."""
        if self._config.interface.tui.auto_copy_selection:
            selected_text = self.screen.get_selected_text()
            if selected_text:
                copy_to_clipboard(selected_text)
                self.screen.clear_selection()
                await self._interface.set_status(
                    status=f"Copied {len(selected_text)} characters to clipboard",
                    duration=2,
                )

    async def ask_question(
        self, question: str, default: str = "", title: str | None = None
    ) -> str:
        """Ask for any kind of input with a prompt."""
        return await self._input_bar.ask_question(question, default, title)

    async def ask_choice(self, question: str, choices, title: str | None = None) -> int:
        """Ask a multiple-choice question using Select widget."""
        return await self._input_bar.ask_choice(question, choices, title)
