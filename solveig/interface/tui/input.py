"""
Unified input widget handling both free-form input and questions.
"""

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import override

from textual.binding import Binding
from textual.containers import Container
from textual.message import Message
from textual.widgets import OptionList, Static, TextArea

from .chat import ChatArea

from ...pending.user_message_queue import UserMessageQueue


class InputMode(Enum):
    """Input widget modes."""

    FREE_FORM = "free_form"
    QUESTION = "question"
    MULTIPLE_CHOICE = "multiple_choice"


@dataclass
class PromptHistory:
    """
    Prompt history, aware of its current index.
    History is kept oldest-first, new entries append at the end, with current
    prompt saved as the final entry while navigating.
    Index is negative and iterates from the end (latest) to the start (oldest.
    """

    entries: list[str] = field(default_factory=list)
    draft: str = ""
    index: int = 0

    @property
    def current(self) -> str:
        return self.entries[self.index] if self.can_go_forward else self.draft

    @property
    def can_go_back(self) -> bool:
        """
        True if there are any stored entries and either the draft
        hasn't been stored yet or index isn't at the end.
        """
        return abs(self.index) < len(self.entries)

    @property
    def can_go_forward(self) -> bool:
        """True if we're accessing history using a negative index."""
        return self.index < 0

    def append(self, text: str):
        """Name implies list semantics that inserts at the end."""
        self.entries.append(text)
        self.index = 0
        self.draft = ""

    def back(self, current: str = "") -> str:
        if self.index == 0:
            self.draft = current
        # Prevent index underflow below list length
        self.index = max(self.index - 1, -len(self.entries))
        return self.current

    def forward(self) -> str:
        # Prevent index overflow into positive values
        self.index = min(0, self.index + 1)
        return self.current


class UserInput(TextArea):
    """A TextArea that grows with content and submits on Enter."""

    BINDINGS = [
        # Requires priority to override the widget's `on_key` which adds '\n' to text
        Binding("enter", "submit", "Submit prompt", priority=True),
        Binding("shift+enter,alt+enter", "insert_newline", "New line", show=False),
        Binding("ctrl+c", "clear_prompt", "Clear", show=False),
        Binding("up", "history_previous", "Previous message", show=False),
        Binding("down", "history_next", "Next message", show=False),
    ]

    def __init__(self, mode: InputMode | Callable[[], InputMode], placeholder: str = "", **kwargs):
        super().__init__(show_line_numbers = False, **kwargs)
        self._mode = mode
        self._history = PromptHistory()
        self.placeholder = placeholder

    @property
    def mode(self) -> InputMode:
        if isinstance(self._mode, InputMode):
            return self._mode
        return self._mode()

    class Submitted(Message):
        """Posted when the user presses Enter."""
        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    @override
    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # NOTE: always return True for "submit", otherwise it defaults to
        #  TextArea's `insert_newline`, and we never want Enter == \n
        if action == "clear_prompt":
            return bool(self.text)
        # TextArea binds Ctrl+C to 'copy', if the input is clear it goes up
        #  and eventually hits the app exit
        # TODO: review
        elif action == "copy":
            return False
        elif action == "history_previous":
            return (
                    self.mode == InputMode.FREE_FORM
                    and self.cursor_at_start_of_text
                    and self._history.can_go_back
            )
        elif action == "history_next":
            return (
                    self.mode is InputMode.FREE_FORM
                    and self.cursor_at_end_of_text
                    and self._history.can_go_forward
            )
        return True

    def action_submit(self) -> None:
        if self.text.strip():
            # Only record user prompts in history, not answers
            if self.mode == InputMode.FREE_FORM:
                self._history.append(self.text)
            self.post_message(self.Submitted(self.text))
            self.text = ""

    def action_clear_prompt(self) -> None:
        self.text = ""

    def action_history_previous(self):
        self.load_text(self._history.back(self.text))

    def action_history_next(self) -> None:
        self.load_text(self._history.forward())

    def action_insert_newline(self) -> None:
        self.insert("\n")


class InputBar(Container):
    """
    Container that manages different input modes: free-form, questions, and multiple choice.
    """

    DEFAULT_INPUT_PLACEHOLDER = "Type and press Enter to send, '/help' for more"

    def __init__(
        self,
        user_message_queue: UserMessageQueue,
        placeholder: str = DEFAULT_INPUT_PLACEHOLDER,
        **kwargs,
    ):
        super().__init__(**kwargs)

        # Mode management
        self._mode = InputMode.FREE_FORM
        self._question_lock = asyncio.Lock()
        self._answer_future: asyncio.Future = asyncio.Future()

        # Callbacks
        self._user_message_queue = user_message_queue

        # Child widgets
        self._text_input = UserInput(
            mode=lambda: self._mode,
            placeholder=placeholder,
            id="text-input",
        )
        self._text_input.placeholder = placeholder
        self._text_input.show_line_numbers = False
        # The framed box a prompt lives in: title on the border (which operation
        # this is about), question inside. Owns whichever prompt widget is up,
        # so tearing it down removes both.
        self._chat: ChatArea

    def compose(self):
        """Create the layout with input widgets."""
        yield self._text_input

    def on_mount(self):
        """Initialize styling when mounted."""
        self._chat = self.app.query_one(ChatArea)
        self._text_input.focus()

    async def on_user_input_submitted(self, event: UserInput.Submitted) -> None:
        """
        Handle the custom Submitted message from the GrowingInput widget.

        HACK: The name is dictated by Textual that translates the classpath
        from a submission's type into its expected handler. Ex: submitting
        `UserInput.Submitted` expects `on_user_input_submitted`.
        """
        user_input = event.value.strip()
        if not user_input:
            return

        if self._mode == InputMode.QUESTION and not self._answer_future.done():
            self._answer_future.set_result(user_input)
        elif self._mode == InputMode.FREE_FORM:
            await self._user_message_queue.put(user_input)

        self._text_input.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option list selection for multiple choice."""
        if self._mode == InputMode.MULTIPLE_CHOICE and not self._answer_future.done():
            self._answer_future.set_result(event.option_index)

    def _apply_free_form_style(self):
        """Apply free-form input styling."""
        self._text_input.remove_class("prompt_input")

    def _apply_question_style(self):
        """Apply question input styling."""
        self._text_input.add_class("prompt_input")

    async def ask_question(
        self, question: str, default: str = "", title: str | None = None
    ) -> str:
        """Switch to question mode and wait for response.

        Same framing as `ask_choice`: title on the border, question on its own
        line inside. It used to live in the input's PLACEHOLDER, which vanished
        the moment you typed - so the thing you were answering disappeared
        exactly when you started answering it."""
        async with self._question_lock:
            saved_text = self._text_input.text
            self._mode = InputMode.QUESTION
            question_box = Container(
                Static(question, classes="prompt_question"),
                classes="prompt_box",
            )
            if title:
                question_box.border_title = title
            await self.mount(question_box, before=self._text_input)

            self._text_input.text = default
            self._apply_question_style()
            self._text_input.focus()

            try:
                return await self._answer_future
            finally:
                # Reset the mode and question future
                self._mode = InputMode.FREE_FORM
                self._answer_future = asyncio.Future()
                await question_box.remove()
                self._text_input.text = saved_text
                self._apply_free_form_style()
                self._text_input.focus()

    async def ask_choice(
        self, question: str, choices: Iterable[str], title: str | None = None
    ) -> int:
        """Show multiple choice selection and wait for response.

        The BORDER carries the title (which operation this is about) and the
        box carries the question. They are deliberately redundant: the title
        only orients, and Textual truncates it to fit the border, while the
        question states the full subject - two commands whose titles truncate
        to the same 40 characters must still be told apart by the thing being
        approved. A prompt raised outside any group has no title and simply
        gets a plain border."""
        choices_list = [
            f"{i + 1}. {choice}"
            for i, choice in enumerate(choices)
        ]

        async with self._question_lock:
            self._mode = InputMode.MULTIPLE_CHOICE
            # Hide text input and show question prompt
            saved_display = self._text_input.styles.display
            self._text_input.styles.display = "none"
            select_widget = OptionList(*choices_list, id="choice_select")
            choice_box = Container(
                Static(question, classes="prompt_question"),
                select_widget,
                classes="prompt_box",
            )
            if title:
                choice_box.border_title = title

            await self.mount(choice_box)
            choice_box.focus()

            try:
                return await self._answer_future
            finally:
                # Reset the mode and the future answer
                self._mode = InputMode.FREE_FORM
                self._answer_future = asyncio.Future()
                # Removing the wrapper takes the option list with it.
                await choice_box.remove()
                # Reset the display mode for the text input and restore focus
                self._text_input.styles.display = saved_display
                self._text_input.focus()

    DEFAULT_CSS = """
        InputBar {
            height: auto;
            margin: 0;
        }

        InputBar > UserInput {
            height: auto;
            min-height: 3;
            color: $foreground;
            background: $background;
            border: solid $border;
            margin: 0;
        }

        /* The frame a prompt lives in. The border carries the title of the
           group the prompt belongs to (Textual truncates it to fit), so two
           prompts open at once say which operation each is for. Without a
           group there is simply no title and the border is plain. */
        .prompt_box {
            height: auto;
            background: $background;
            border: solid $border;
            border-title-style: bold;
            margin: 0;
            padding: 0 1;
        }

        /* The free-form input is a plain $border border; when a question prompt
           raises it switches to $input. Both come from the theme via CSS, so
           a runtime theme change re-resolves them (the border can not be set
           inline - that would freeze the init-time Palette). */
        InputBar > UserInput.prompt_input {
            border: solid $input;
        }

        /* The question itself, inside the frame and never shortened - it names
           the full subject being approved, which the title may not. */
        .prompt_question {
            height: auto;
            width: 100%;
            color: $foreground;
            margin: 0 0 1 0;
            padding: 0;
        }

        .prompt_box > OptionList {
            height: auto;
            color: $foreground;
            background: $background;
            border: none;
            margin: 0;
            padding: 0;
        }

        .prompt_box > OptionList > *.option-list--option-highlighted {
            background: $input;
            color: $foreground;
        }

        InputBar > Static {
            height: 1;
            color: $input;
            margin: 0;
        }
        """
