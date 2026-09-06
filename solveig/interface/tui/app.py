"""Main Textual application class."""

import asyncio

from textual import events
from textual.app import App as TextualApp
from textual.app import ComposeResult

from solveig.interface.base import SolveigInterface
from solveig.interface.themes import THEMES, to_textual_theme
from solveig.pending.user_message_queue import UserMessageQueue
from solveig.utils.misc import copy_to_clipboard

from .conversation_area import ConversationArea
from .input_bar import InputBar
from .keys import TASK_CANCEL_KEYS
from .queued_messages import QueuedMessagesDisplay
from .stats_bar import StatsBar
from ...config import SolveigConfig


class SolveigTextualApp(TextualApp):
    """
    Minimal TextualApp subclass with only essential Solveig customizations.
    """

    # CSS is theme-independent (colours come from $variables resolved against the
    # active Textual theme), so it's a static class attribute assembled once - no
    # per-instance rebuild, and runtime theme changes are handled by `self.theme`.
    CSS = (
        """
        Screen {
            background: $background;
            color: $foreground;
        }

        .info_message { color: $info; }
        .warning_message { color: $warning; }
        .error_message { color: $error; }
        """
        + ConversationArea.get_css()
        + InputBar.get_css()
        + StatsBar.get_css()
        + QueuedMessagesDisplay.get_css()
    )

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
        for palette in THEMES.values():
            self.register_theme(to_textual_theme(palette))

        # This is the actual theme name that Textual will use, not a Palette
        self.theme = self._config.interface.tui.theme.name

        # Register an observer for the code value
        @self._config.on_change("interface.tui.theme")
        async def _on_theme_change(_config, paths):
            self.theme = _config.interface.tui.theme.name

        # Cached widget references (set in on_mount)
        self._conversation_area: ConversationArea
        self._input_widget: InputBar
        self._stats_dashboard: StatsBar
        self._queued_messages_display: QueuedMessagesDisplay

        # Readiness event
        self.is_ready = asyncio.Event()

    def compose(self) -> ComposeResult:
        """Create the main layout."""
        yield ConversationArea()
        yield QueuedMessagesDisplay(self._user_message_queue)
        yield InputBar(
            self._user_message_queue,
        )
        yield StatsBar(
            config=self._config,
            interface=self._interface,
        )

    def on_mount(self) -> None:
        """Called when the app is mounted and widgets are available."""
        # Cache widget references
        self._conversation_area = self.query_one(ConversationArea)
        self._input_widget = self.query_one(InputBar)
        self._stats_dashboard = self.query_one(StatsBar)
        self._queued_messages_display = self.query_one(QueuedMessagesDisplay)

        # Focus the input widget so user can start typing immediately
        self._input_widget.focus()

    def on_ready(self) -> None:
        # Announce interface is ready
        self.is_ready.set()

    async def on_key(self, event) -> None:
        """Handle key events directly.

        A task-cancel key (see `keys.TASK_CANCEL_KEYS`, which the status hint is
        also built from):
        - If there's an active network request: cancel it
        - Otherwise: exit the application
        """
        if event.key in TASK_CANCEL_KEYS:
            # Check if there's an active operation via the interface
            if self._interface.get_active_tasks():
                event.stop()
                self._interface.cancel_task()
            else:
                self.exit()

    async def on_event(self, event) -> None:
        """Intercept mouse-up to auto-copy a completed click-drag text selection."""
        await super().on_event(event)
        # Read live rather than cached at construction, so toggling the setting
        # takes effect on the next selection instead of the next launch.
        auto_copy = (
            self._config is None or self._config.interface.tui.auto_copy_selection
        )
        if auto_copy and isinstance(event, events.MouseUp):
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
        return await self._input_widget.ask_question(question, default, title)

    async def ask_choice(self, question: str, choices, title: str | None = None) -> int:
        """Ask a multiple-choice question using Select widget."""
        return await self._input_widget.ask_choice(question, choices, title)
