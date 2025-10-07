"""
Simple CLI interface for Solveig - fallback implementation without Textual.
"""

import random
import shutil
from contextlib import contextmanager, asynccontextmanager
from typing import Optional, Callable, Union, Awaitable, AsyncGenerator, Any

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML, FormattedText
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console, Text

from solveig.interface.base import SolveigInterface
from solveig.interface.themes import terracotta, Palette


class SimpleInterface(SolveigInterface):
    """Simple CLI interface implementation using Rich and prompt_toolkit."""

    DEFAULT_INPUT_PROMPT = ">"
    PADDING_LEFT = Text(" ")
    PADDING_RIGHT = Text(" ")

    class TEXT_BOX:
        H = "─"
        V = "│"
        TL = "┌"
        TR = "┐"
        BL = "└"
        BR = "┘"
        VL = "┤"
        VR = "├"
        HB = "┬"
        HT = "┴"
        X = "┼"

    # Allowed spinners (built-in Rich + our custom ones)
    ALLOWED_SPINNERS = {
        "star",
        "dots3",
        "dots10",
        "balloon",
        # Custom spinners
        "growing",
        "cool",
    }

    def __init__(self, color_palette: Palette = terracotta, animation_interval: float = 0.1, **kwargs):
        self.color_palette = color_palette
        self.animation_interval = animation_interval
        self.input_callback: Optional[Callable[[SolveigInterface, str], Union[None, Awaitable[None]]]] = None

        self.output_console = Console()
        self.input_console: PromptSession = PromptSession(
            color_depth=ColorDepth.TRUE_COLOR
        )
        self._input_style_dict = self._create_prompt_toolkit_style()

        self._setup_custom_spinners()

    def _get_max_output_width(self) -> int:
        return (
            shutil.get_terminal_size((80, 20)).columns
            - len(self.PADDING_LEFT)
            - len(self.PADDING_RIGHT)
        )

    def _output(self, text: str | Text, pad: bool = True, **kwargs) -> None:
        self.output_console.print(
            (self.PADDING_LEFT if pad else Text(""))
            + text
            + (self.PADDING_RIGHT if pad else Text("")),
            **kwargs,
        )

    def _create_prompt_toolkit_style(self):
        """Create prompt_toolkit style from color palette."""
        return {
            'prompt': f'fg:{self.color_palette.prompt}',
            'text': f'fg:{self.color_palette.text}',
            'error': f'fg:{self.color_palette.error}',
            'warning': f'fg:{self.color_palette.warning}',
        }

    def _setup_custom_spinners(self):
        """Set up custom spinners for Rich animations."""
        from rich._spinners import SPINNERS as RICH_SPINNERS

        # Add custom spinners to Rich's SPINNERS dictionary
        RICH_SPINNERS["growing"] = {
            "interval": 150,
            "frames": ["🤆", "🤅", "🤄", "🤃", "🤄", "🤅", "🤆"],
        }
        RICH_SPINNERS["cool"] = {
            "interval": 120,
            "frames": ["⨭", "⨴", "⨂", "⦻", "⨂", "⨵", "⨮", "⨁"],
        }

        # Pad the spinners
        for spinner in self.ALLOWED_SPINNERS:
            frames = RICH_SPINNERS[spinner]["frames"]
            RICH_SPINNERS[spinner]["frames"] = [
                f"{self.PADDING_LEFT}{frame}" for frame in frames
            ]

    async def _input(self, prompt: str, multiline: bool = False, **kwargs) -> str:
        """Enhanced async input with multi-line support and helpful toolbar."""
        try:
            with patch_stdout():
                toolbar_text = "Type your input above. "
                if multiline:
                    toolbar_text += "Alt+Enter or Ctrl+J for new line. "
                toolbar_text += "Press Enter to submit, Ctrl+C to cancel."

                result = await self.input_console.prompt_async(
                    FormattedText([('class:prompt', f"{self.PADDING_LEFT}{prompt}")]),
                    style=self._input_style_dict,
                    bottom_toolbar=toolbar_text,
                    multiline=multiline,
                    **kwargs
                )
            return result
        except KeyboardInterrupt:
            raise

    # SolveigInterface implementation
    def display_text(self, text: str, style: str = "normal") -> None:
        """Display text with optional styling."""
        if style == "error":
            color = self.color_palette.error
        elif style == "warning":
            color = self.color_palette.warning
        elif style == "success":
            color = self.color_palette.group
        elif style == "system":
            color = self.color_palette.group
        elif style == "user":
            color = self.color_palette.prompt
        else:
            color = self.color_palette.text

        self._output(Text(text, style=color))

    def display_error(self, error: str) -> None:
        """Display an error message with standard formatting."""
        self.display_text(f"❌ Error: {error}", "error")

    def display_warning(self, warning: str) -> None:
        """Display a warning message with standard formatting."""
        self.display_text(f"⚠️  Warning: {warning}", "warning")

    def display_success(self, message: str) -> None:
        """Display a success message with standard formatting."""
        self.display_text(f"✅ {message}", "success")

    def display_comment(self, message: str) -> None:
        """Display a comment message."""
        self.display_text(message, "system")

    def display_text_block(self, text: str, title: str = None) -> None:
        """Display a text block with optional title."""
        max_width = self._get_max_output_width()

        # Top bar
        top_bar = Text(f"{self.TEXT_BOX.TL}", style=self.color_palette.group)
        if title:
            top_bar.append(f"{self.TEXT_BOX.H * 3}")
            top_bar.append(f" {title} ", style=f"bold {self.color_palette.group}")
        top_bar.append(
            f"{self.TEXT_BOX.H * (max_width - len(top_bar) - 2)}{self.TEXT_BOX.TR}"
        )
        self._output(top_bar)

        # Content lines
        vertical_bar_left = Text(f"{self.TEXT_BOX.V} ", style=self.color_palette.group)
        vertical_bar_right = Text(f" {self.TEXT_BOX.V} ", style=self.color_palette.group)
        max_line_length = max_width - len(vertical_bar_left) - len(vertical_bar_right)

        lines = text.splitlines()
        for line in lines:
            if len(line) > max_line_length:
                truncated_line = f"{line[0:max_line_length - 3]}..."
            else:
                truncated_line = f"{line}{' ' * (max_line_length - len(line))}"
            line_text = Text(truncated_line, style=self.color_palette.text)
            self._output(vertical_bar_left + line_text + vertical_bar_right)

        # Bottom bar
        self._output(
            f"{self.TEXT_BOX.BL}{self.TEXT_BOX.H * (max_width - 3)}{self.TEXT_BOX.BR}",
            style=self.color_palette.group,
        )

    async def ask_user(self, prompt: str, placeholder: str = None, multiline: bool = False) -> str:
        """Ask for specific input with optional multi-line support."""
        if multiline:
            full_prompt = f"{prompt}: "
            self.display_text("📝 Multi-line input mode enabled. Use Alt+Enter for new lines.", "system")
        else:
            full_prompt = f"{prompt}: "
        return await self._input(full_prompt, multiline=multiline)

    async def get_input(self) -> str:
        """Get user input for conversation flow."""
        return await self._input("💬 ")

    async def ask_yes_no(self, question: str, yes_values=None, no_values=None) -> bool:
        """Ask a yes/no question."""
        if yes_values is None:
            yes_values = ["y", "yes", "1", "true", "t"]
        if no_values is None:
            no_values = ["n", "no", "0", "false", "f", ""]

        response = await self.ask_user(question, f"❓ {question} [y/N]")
        result = response.lower().strip() in yes_values

        self.display_text(f"❓ {question} → {'Yes' if result else 'No'}", "system")
        return result

    def set_status(self, status: str) -> None:
        """Update status display (if supported)."""
        self.display_text(f"Status: {status}", "system")

    async def start(self) -> None:
        """Start the interface (if needed)."""
        pass

    async def stop(self) -> None:
        """Stop the interface (if needed)."""
        pass

    def display_section(self, title: str) -> None:
        """Display a section header."""
        terminal_width = (
            self._get_max_output_width()
            + len(self.PADDING_LEFT)
            + len(self.PADDING_RIGHT)
        )
        title_formatted = f"{self.TEXT_BOX.H * 3} {title} " if title else ""
        padding = (
            self.TEXT_BOX.H * (terminal_width - len(title_formatted))
            if terminal_width > 0
            else ""
        )
        self._output(
            f"\n\n{title_formatted}{padding}",
            style=f"bold {self.color_palette.group}",
            pad=False,
        )

    @contextmanager
    def with_group(self, title: str):
        """Context manager for grouping related output."""
        self.display_text(f"[ {title} ]", "system")
        try:
            yield
        finally:
            pass

    @asynccontextmanager
    async def with_animation(self, status: str = "Processing", final_status: str = "Ready") -> AsyncGenerator[None, Any]:
        """Async context manager for displaying animation during operations."""
        # Pick random spinner
        animation_type = random.choice(list(self.ALLOWED_SPINNERS))
        display_message = status
        style = self.color_palette.prompt

        # Use Rich status for styled animation
        with self.output_console.status(
            Text(
                f"{self.PADDING_LEFT}{display_message}{self.PADDING_RIGHT}", style=style
            ),
            spinner=animation_type,
            spinner_style=style,
        ):
            try:
                yield
            finally:
                # Clear the status and show final message if different
                if final_status != status:
                    self.set_status(final_status)

    def display_animation_while(
        self,
        run_this: Callable,
        message: str = None,
        animation_type: str = None,
        style: str = None,
    ) -> Any:
        """Display animation while running a function."""
        style = style or self.color_palette.prompt

        # Pick random spinner if none specified
        if animation_type is None:
            animation_type = random.choice(list(self.ALLOWED_SPINNERS))

        # Assert the spinner is in our allowed set
        assert (
            animation_type in self.ALLOWED_SPINNERS
        ), f"Spinner '{animation_type}' not in allowed set: {self.ALLOWED_SPINNERS}"

        display_message = message or "Processing..."

        # Use Rich status for styled animation that integrates with console
        with self.output_console.status(
            Text(
                f"{self.PADDING_LEFT}{display_message}{self.PADDING_RIGHT}", style=style
            ),
            spinner=animation_type,
            spinner_style=style,
        ):
            return run_this()


