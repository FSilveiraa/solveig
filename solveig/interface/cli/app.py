"""Main Textual application class."""

import asyncio

from textual.app import App as TextualApp
from textual.app import ComposeResult

from solveig.interface.themes import DEFAULT_THEME, Palette

from .conversation import ConversationArea
from .input_bar import InputBar
from .status_bar import StatusBar

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

        # Get color mapping and create CSS
        self._style_to_color = color_palette.to_textual_css()
        self._color_to_style = {
            color: name for name, color in self._style_to_color.items()
        }

        # Generate CSS from the color dict
        css_rules = []
        for name, color in self._style_to_color.items():
            css_rules.append(f".{name}_message {{ color: {color}; }}")

        # Set CSS as class attribute for Textual
        SolveigTextualApp.CSS = f"""
        Screen {{
            background: {self._style_to_color["background"]};
            color: {self._style_to_color["text"]};
        }}

        ConversationArea {{
            height: 1fr;
        }}


        StatusBar {{
            dock: bottom;
            height: 1;
            content-align: center middle;
        }}

        TextBox {{
            border: solid {self._style_to_color.get("box", "#000")};
            margin: 1;
            padding: 0 1;
        }}

        SectionHeader {{
            color: {self._style_to_color.get("section", "#fff")};
            text-style: bold;
            margin: 1 0;
            padding: 0 0;
        }}

        .group_container {{
            border-left: heavy {self._style_to_color.get("group", "#888")};
            padding-left: 1;
            margin: 0 0 0 1;
            height: auto;
            min-height: 0;
        }}

        .group_bottom {{
            color: {self._style_to_color["group"]};
            margin: 0 0 1 1;
        }}

        .group_top {{
            color: {self._style_to_color["group"]};
            margin: 1 0 0 1;
        }}

        {"\n".join(css_rules)}

        {InputBar.get_css(color_palette)}
        """


        # Cached widget references (set in on_mount)
        self._conversation_area: ConversationArea
        self._input_widget: InputBar
        self._status_bar: StatusBar

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
        yield StatusBar(id="status")

    def on_mount(self) -> None:
        """Called when the app is mounted and widgets are available."""
        # Cache widget references
        self._conversation_area = self.query_one("#conversation", ConversationArea)
        self._input_widget = self.query_one("#input", InputBar)
        self._status_bar = self.query_one("#status", StatusBar)
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