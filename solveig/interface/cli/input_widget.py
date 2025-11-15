"""
Unified input widget handling both free-form input and questions.
"""

import asyncio
from enum import Enum

from collections.abc import Iterable

from textual.containers import Container, Vertical
from textual.widgets import Input, OptionList, Static

from solveig.interface.themes import Palette


class InputMode(Enum):
    """Input widget modes."""
    FREE_FORM = "free_form"
    QUESTION = "question"
    MULTIPLE_CHOICE = "multiple_choice"


class InputBar(Container):
    """
    Container that manages different input modes: free-form, questions, and multiple choice.
    """

    def __init__(
        self,
        *,
        placeholder: str = "",
        theme: Palette,
        free_form_callback=None,
        **kwargs
    ):
        super().__init__(**kwargs)

        # Theme and styling
        self._theme = theme
        self._style_to_color = theme.to_textual_css()

        # Mode management
        self._mode = InputMode.FREE_FORM
        self._question_future: asyncio.Future | None = None
        self._choice_future: asyncio.Future | None = None

        # Callbacks
        self._free_form_callback = free_form_callback

        # Child widgets
        self._text_input = Input(placeholder=placeholder, id="text_input")
        self._select_widget = None
        # self._prompt_label = Static("", id="prompt_label")

        # Saved state for question mode
        self._saved_text: str = ""
        self._saved_placeholder: str = placeholder

    def compose(self):
        """Create the layout with input widgets."""
        # yield Rule(line_style="heavy", id="input_separator")
        # yield self._prompt_label
        yield self._text_input

    def on_mount(self):
        """Initialize styling when mounted."""
        self._apply_free_form_style()
        self._text_input.focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle text input submission."""
        if event.input.id != "text_input":
            return

        user_input = event.value.strip()
        event.input.value = ""

        if self._mode == InputMode.QUESTION and self._question_future:
            if not self._question_future.done():
                self._question_future.set_result(user_input)
        elif self._mode == InputMode.FREE_FORM and self._free_form_callback:
            if asyncio.iscoroutinefunction(self._free_form_callback):
                asyncio.create_task(self._free_form_callback(user_input))
            else:
                self._free_form_callback(user_input)

        event.input.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option list selection for multiple choice."""
        if self._mode == InputMode.MULTIPLE_CHOICE and self._choice_future:
            if not self._choice_future.done():
                # Get the index from the event
                selected_index = event.option_index
                self._choice_future.set_result(selected_index)

    def _apply_free_form_style(self):
        """Apply free-form input styling."""
        self._text_input.styles.border = ("solid", self._style_to_color["prompt"])

    def _apply_question_style(self):
        """Apply question input styling."""
        self._text_input.styles.border = ("solid", self._style_to_color["warning"])

    async def ask_question(self, question: str) -> str:
        """Switch to question mode and wait for response."""
        self._saved_text = self._text_input.value
        self._saved_placeholder = self._text_input.placeholder

        self._mode = InputMode.QUESTION
        self._question_future = asyncio.Future()

        self._text_input.value = ""
        self._text_input.placeholder = question
        # self._prompt_label.update(question)
        self._apply_question_style()
        self._text_input.focus()

        try:
            response = await self._question_future
            return response
        finally:
            self._mode = InputMode.FREE_FORM
            self._question_future = None
            self._text_input.placeholder = self._saved_placeholder
            self._text_input.value = self._saved_text
            # self._prompt_label.update("")
            self._apply_free_form_style()
            self._text_input.focus()

    async def ask_choice(self, question: str, choices: Iterable[str]) -> int:
        """Show multiple choice selection and wait for response."""
        choices_list = list(choices)

        self._mode = InputMode.MULTIPLE_CHOICE
        self._choice_future = asyncio.Future()

        # Hide text input and show question prompt
        self._text_input.styles.display = "none"
        # self._prompt_label.update(question)

        # Create option list widget with choices and mount in place of input
        options = [f"{i+1}. {choice}" for i, choice in enumerate(choices_list)]
        self._select_widget = OptionList(*options, id="choice_select")
        self._select_widget.border_title = question

        # Mount inside this container
        await self.mount(self._select_widget)
        self._select_widget.focus()

        # OptionList doesn't need to be expanded

        try:
            selected_index = await self._choice_future
            return selected_index
        finally:
            # Clean up and restore text input
            self._mode = InputMode.FREE_FORM
            self._choice_future = None
            if self._select_widget:
                await self._select_widget.remove()
                self._select_widget = None
            # self._prompt_label.update("")
            self._text_input.styles.display = "block"
            self._text_input.focus()


    @classmethod
    def get_css(cls, theme: Palette) -> str:
        """Generate CSS for this widget container."""
        style_to_color = theme.to_textual_css()

        return f"""
        InputBar {{
            dock: bottom;
            height: auto;
            margin: 0 0 1 0;
        }}

        InputBar > Input {{
            height: 3;
            color: {style_to_color["text"]};
            background: {style_to_color["background"]};
            border: solid {style_to_color["prompt"]};
            margin: 0;
        }}

        InputBar > OptionList {{
            height: auto;
            color: {style_to_color["text"]};
            background: {style_to_color["background"]};
            border: solid {style_to_color["prompt"]};
            margin: 0;
        }}
        
        InputBar > OptionList > *.option-list--option-highlighted {{
            background: {style_to_color["prompt"]};
        }}

        InputBar > Static {{
            height: 1;
            color: {style_to_color["prompt"]};
            margin: 0;
        }}

        InputBar > Input > .input--placeholder {{
            text-style: italic;
        }}
        
        #prompt_label {{
            text-style: bold;
            height: auto;
            min-height: 0;
            margin: 0;
        }}
        
        #input_separator {{
            margin: 0;
            color: {style_to_color["prompt"]};
        }}
        """