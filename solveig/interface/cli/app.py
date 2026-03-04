"""Main Textual application class."""

import asyncio

from textual.app import App as TextualApp
from textual.app import ComposeResult

from solveig.interface.themes import DEFAULT_THEME, Palette
from solveig.schema.message.pending import PendingMessageQueue

from .conversation import ConversationArea
from .input_bar import InputBar
from .queued_messages import QueuedMessagesDisplay
from .stats_bar import StatsBar

DEFAULT_INPUT_PLACEHOLDER = (
    "Click to focus, type and press Enter to send, '/help' for more"
)


class SolveigTextualApp(TextualApp):
    """
    Minimal TextualApp subclass with only essential Solveig customizations.
    """

    def __init__(
        self,
        theme: Palette = DEFAULT_THEME,
        input_callback=None,
        pending_queue: PendingMessageQueue | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._input_callback = input_callback
        self._theme = theme
        self._pending_queue = pending_queue

        # Set CSS as class attribute for Textual
        SolveigTextualApp.CSS = f"""
        Screen {{
            background: {theme.background};
            color: {theme.text};
        }}

        .text_message {{ color: {theme.text}; }}
        .info_message {{ color: {theme.info}; }}
        .warning_message {{ color: {theme.warning}; }}
        .error_message {{ color: {theme.error}; }}

        {ConversationArea.get_css(theme)}
        {InputBar.get_css(theme)}
        {StatsBar.get_css(theme)}
        {QueuedMessagesDisplay.get_css(theme)}
        """

        # Cached widget references (set in on_mount)
        self._conversation_area: ConversationArea
        self._input_widget: InputBar
        self._stats_dashboard: StatsBar
        self._queued_messages_display: QueuedMessagesDisplay | None = None

        # Readiness event
        self.is_ready = asyncio.Event()

    def compose(self) -> ComposeResult:
        """Create the main layout."""
        yield ConversationArea(id="conversation")

        # Queued messages display (only if queue provided)
        if self._pending_queue is not None:
            yield QueuedMessagesDisplay(
                queue=self._pending_queue,
                theme=self._theme,
                id="queued_messages",
            )

        yield InputBar(
            placeholder=DEFAULT_INPUT_PLACEHOLDER,
            theme=self._theme,
            free_form_callback=self._input_callback,
            id="input",
        )

        yield StatsBar(
            id="stats",
            theme=self._theme,
        )

    def on_mount(self) -> None:
        """Called when the app is mounted and widgets are available."""
        # Cache widget references
        self._conversation_area = self.query_one("#conversation", ConversationArea)
        self._input_widget = self.query_one("#input", InputBar)
        self._stats_dashboard = self.query_one("#stats", StatsBar)

        if self._pending_queue is not None:
            self._queued_messages_display = self.query_one(
                "#queued_messages", QueuedMessagesDisplay
            )

        # Focus the input widget so user can start typing immediately
        self._input_widget.focus()

    def update_queued_display(self):
        """Update the queued messages display.

        Call this after queue changes to refresh the UI.
        """
        if self._queued_messages_display is not None:
            self._queued_messages_display.update_display()

    def on_ready(self) -> None:
        # Announce interface is ready
        self.is_ready.set()

    async def on_key(self, event) -> None:
        """Handle key events directly.

        Ctrl+C behavior:
        - If there's an active network request: cancel it
        - Otherwise: exit the application
        """
        if event.key == "ctrl+c":
            # Check if there's an active network request via the interface
            interface = getattr(self, "_interface_ref", None)
            if interface is not None and interface.has_active_request:
                event.stop()
                interface.cancel_request()
            else:
                self.exit()

    def set_interface_ref(self, interface) -> None:
        """Store a reference to the interface for cancellation checks."""
        self._interface_ref = interface

    async def ask_user(self, question: str) -> str:
        """Ask for any kind of input with a prompt."""
        return await self._input_widget.ask_question(question)

    async def ask_choice(self, question: str, choices) -> int:
        """Ask a multiple-choice question using Select widget."""
        return await self._input_widget.ask_choice(question, choices)

    async def add_text(
        self, text: str, style: str = "text", markup: bool = False
    ) -> None:
        """Internal method to add text to the UI."""
        await self._conversation_area.add_text(text, style, markup=markup)
