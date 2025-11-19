"""Main Textual application class."""

import asyncio

from textual.app import App as TextualApp
from textual.app import ComposeResult
from textual.widgets import Collapsible, DataTable

from solveig.interface.themes import DEFAULT_THEME, Palette

from .conversation import ConversationArea
from .input_bar import InputBar
from .stats_dashboard import StatsDashboard
from .stats_bar import create_stats_content

DEFAULT_INPUT_PLACEHOLDER = (
    "Click to focus, type and press Enter to send, '/help' for more"
)


class SolveigTextualApp(TextualApp):
    """
    Minimal TextualApp subclass with only essential Solveig customizations.
    """

    def __init__(
        self,
        color_palette: Palette = DEFAULT_THEME,
        input_callback=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._input_callback = input_callback
        self._theme = color_palette

        # Set CSS as class attribute for Textual
        SolveigTextualApp.CSS = f"""
        Screen {{
            background: {color_palette.background};
            color: {color_palette.text};
        }}

        .text_message {{ color: {color_palette.text}; }}
        .info_message {{ color: {color_palette.info}; }}
        .warning_message {{ color: {color_palette.warning}; }}
        .error_message {{ color: {color_palette.error}; }}

        {ConversationArea.get_css(color_palette)}
        {InputBar.get_css(color_palette)}

        .separator {{
            width: 1;
            height: 100%;
            border: none;
            color: {color_palette.box};
            text-align: center;
        }}

        #stats {{
            dock: bottom;
            height: auto;
            max-height: 8;
        }}
        """

        # Cached widget references (set in on_mount)
        self._conversation_area: ConversationArea
        self._input_widget: InputBar
        self._stats_dashboard: StatsDashboard

        # Readiness event
        self.is_ready = asyncio.Event()

    def compose(self) -> ComposeResult:
        """Create the main layout."""
        yield ConversationArea(id="conversation")

        yield InputBar(
            placeholder=DEFAULT_INPUT_PLACEHOLDER,
            theme=self._theme,
            free_form_callback=self._input_callback,
            id="input",
        )

        with Collapsible(title="Stats", collapsed=True, id="stats"):
            yield create_stats_content()

    def on_mount(self) -> None:
        """Called when the app is mounted and widgets are available."""
        # Cache widget references
        self._conversation_area = self.query_one("#conversation", ConversationArea)
        self._input_widget = self.query_one("#input", InputBar)
        self._stats_dashboard = self.query_one("#stats", Collapsible)
        # Add dummy method for compatibility
        self._stats_dashboard.update_status_info = lambda **kwargs: None
        # Focus the input widget so user can start typing immediately
        self._input_widget.focus()

    def on_ready(self) -> None:
        # Announce interface is ready
        self.is_ready.set()


    async def on_key(self, event) -> None:
        """Handle key events directly."""
        if event.key == "ctrl+c":
            self.exit()

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