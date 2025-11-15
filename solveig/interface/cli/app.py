"""Main Textual application class."""

import asyncio

from textual.app import App as TextualApp
from textual.app import ComposeResult
from textual.widgets import Input

from solveig.interface.themes import DEFAULT_THEME, Palette

from .conversation import ConversationArea
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

        Input {{
            dock: bottom;
            height: 3;
            color: {self._style_to_color["text"]};
            background: {self._style_to_color["background"]};
            border: solid {self._style_to_color["prompt"]};
            margin: 0 0 1 0;
        }}

        Input > .input--placeholder {{
            text-style: italic;
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
        """

        # Prompt handling state
        self.prompt_future: asyncio.Future | None = None
        self._saved_input_text: str = ""
        self._original_placeholder: str = ""

        # Cached widget references (set in on_mount)
        self._conversation_area: ConversationArea
        self._input_widget: Input
        self._status_bar: StatusBar

        # Readiness event
        self.is_ready = asyncio.Event()

    def compose(self) -> ComposeResult:
        """Create the main layout."""
        yield ConversationArea(id="conversation")
        yield Input(
            placeholder=DEFAULT_INPUT_PLACEHOLDER,
            id="input",
        )
        yield StatusBar(id="status")

    def on_mount(self) -> None:
        """Called when the app is mounted and widgets are available."""
        # Cache widget references
        self._conversation_area = self.query_one("#conversation", ConversationArea)
        self._input_widget = self.query_one("#input", Input)
        self._status_bar = self.query_one("#status", StatusBar)
        # Focus the input widget so user can start typing immediately
        self._input_widget.focus()

    def on_ready(self) -> None:
        # Announce interface is ready
        self.is_ready.set()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input submission."""
        user_input = event.value.strip()
        event.input.value = ""  # Clear input

        # Check if we're in prompt mode (waiting for specific answer)
        if self.prompt_future and not self.prompt_future.done():
            # Prompt mode: just fulfill the future
            self.prompt_future.set_result(user_input)
        else:
            # Free-flow mode: use callback if provided
            if self._input_callback:
                if asyncio.iscoroutinefunction(self._input_callback):
                    asyncio.create_task(self._input_callback(user_input))
                else:
                    self._input_callback(user_input)

        # Keep focus on input after submission
        event.input.focus()

    async def on_key(self, event) -> None:
        """Handle key events directly."""
        if event.key == "ctrl+c":
            self.exit()

    async def ask_user(self, prompt: str, placeholder: str | None = None) -> str:
        """Ask for any kind of input with a prompt."""
        try:
            # Save current state
            self._saved_input_text = self._input_widget.value
            self._original_placeholder = self._input_widget.placeholder

            # Set up prompt
            self.prompt_future = asyncio.Future()
            self._input_widget.value = ""
            self._input_widget.placeholder = placeholder or prompt
            self._input_widget.styles.border = (
                "solid",
                self._style_to_color["warning"],
            )

            # Focus the input
            self._input_widget.focus()

            # Wait for response
            response = await self.prompt_future

            # Restore state
            self._input_widget.placeholder = self._original_placeholder
            self._input_widget.value = self._saved_input_text
            self._input_widget.styles.border = ("solid", self._style_to_color["prompt"])

            # Restore focus
            self._input_widget.focus()

            return response

        finally:
            self.prompt_future = None

    async def add_text(
        self, text: str, style: str = "text", markup: bool = False
    ) -> None:
        """Internal method to add text to the UI."""
        await self._conversation_area.add_text(text, style, markup=markup)