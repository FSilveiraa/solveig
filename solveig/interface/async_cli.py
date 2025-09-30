"""
Working async CLI interface using prompt_toolkit for input bar + Rich for static content.
"""

import asyncio
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console

from .cli import CLIInterface


class AsyncCLIInterface(CLIInterface):
    """Async CLI interface using prompt_toolkit bottom bar + Rich static content."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.input_queue: asyncio.Queue = asyncio.Queue()
        self.waiting_for_input = False
        self.waiting_for_yn = False
        self.yn_future: Optional[asyncio.Future] = None
        self.session: Optional[PromptSession] = None
        self.saved_input_buffer = ""  # Save partial input during y/n interrupts

    async def get_user_input(self) -> str:
        """Get user input from the permanent input bar."""
        self.waiting_for_input = True

        # Wait for input to be submitted
        result = await self.input_queue.get()
        self.waiting_for_input = False
        return result

    async def ask_yes_no_async(self, question: str, yes_values=None, no_values=None) -> bool:
        """Non-blocking y/n - shows question and waits for next user message."""
        if yes_values is None:
            yes_values = ["y", "yes", "1", "true", "t"]
        if no_values is None:
            no_values = ["n", "no", "0", "false", "f", ""]

        # Display the question using Rich
        self.display_text(f"❓ {question} (answer with your next message)")

        # Wait for the next user input (doesn't matter if they're already typing)
        response = await self.get_user_input()

        # Parse their response
        result = response.lower().strip() in yes_values

        # Display the result using Rich
        self.display_text(f"✅ {'Yes' if result else 'No'}")

        return result

    async def input_listener(self):
        """Background coroutine that listens for keyboard input using prompt_toolkit."""
        self.session = PromptSession()

        while True:
            try:
                with patch_stdout():
                    if self.waiting_for_input:
                        # Handle regular input with persistent bottom toolbar
                        user_input = await self.session.prompt_async(
                            FormattedText([('class:prompt', '> ')]),
                            style=self._input_style_dict,
                            bottom_toolbar="Type your message and press Enter"
                        )
                        # Immediately echo what was typed
                        self.display_text(f"👤 You: {user_input}")
                        await self.input_queue.put(user_input)

                    else:
                        # Not waiting for input, just sleep briefly
                        await asyncio.sleep(0.1)

            except KeyboardInterrupt:
                break
            except Exception as e:
                # Display error using Rich
                self.display_error(f"Input error: {e}")
                await asyncio.sleep(0.1)

    # Display methods use Rich Console for static output (no Live display)
    def display_text(self, text: str, style: str | None = None, **kwargs):
        """Display text using Rich Console (static)."""
        with patch_stdout():
            super().display_text(text, style, **kwargs)

    def display_section(self, title: str, level: int | None = None):
        """Display section header using Rich Console."""
        with patch_stdout():
            super().display_section(title, level)

    def display_error(self, error: Exception | str, level: int | None = None):
        """Display error using Rich Console."""
        with patch_stdout():
            super().display_error(error, level)

    def display_warning(self, warning: str, level: int | None = None):
        """Display warning using Rich Console."""
        with patch_stdout():
            super().display_warning(warning, level)

    # Sync wrapper methods for compatibility with existing requirement.solve() calls
    def ask_user(self, question: str = None, level: int | None = None, **kwargs) -> str:
        """Sync wrapper for existing code."""
        if question is None:
            question = self.DEFAULT_INPUT_PROMPT

        # Use the existing CLIInterfaceWithInputBar approach for sync calls
        return super().ask_user(question, level, **kwargs)

    def ask_yes_no(self, question: str, yes_values=None, no_values=None, **kwargs) -> bool:
        """Sync wrapper for existing code."""
        # Use the existing CLIInterface approach for sync calls
        return super().ask_yes_no(question, yes_values, no_values, **kwargs)