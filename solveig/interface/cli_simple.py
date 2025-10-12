"""
Simple CLI interface for Solveig - fallback implementation without Textual.
"""

import random
import asyncio
import shutil
from contextlib import contextmanager, asynccontextmanager
from datetime import datetime
from typing import Optional, Callable, Union, Awaitable, AsyncGenerator, Any

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML, FormattedText
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console, Text

from solveig.interface.base import SolveigInterface
from solveig.interface.themes import terracotta, Palette
from solveig.utils.file import Metadata
import solveig.utils.misc


class SimpleInterface(SolveigInterface):
    """Simple CLI interface implementation using Rich and prompt_toolkit."""

    DEFAULT_INPUT_PROMPT = ">"
    PADDING_LEFT = Text(" ")
    PADDING_RIGHT = Text(" ")
    YES = { "y", "yes" }

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

    def __init__(self, color_palette: Palette = terracotta, animation_interval: float = 0.1, indent_base: int = 2, **kwargs):
        self.color_palette = color_palette
        self.animation_interval = animation_interval
        self.indent_base = indent_base
        self._current_indent = ""  # The actual indent string
        self._stop_event: asyncio.Event = asyncio.Event()

        self.output_console = Console()
        self.input_console: PromptSession = PromptSession(
            color_depth=ColorDepth.TRUE_COLOR
        )
        self._input_style = self.color_palette.to_prompt_toolkit_style()
        self._setup_custom_spinners()

    async def wait_until_ready(self):
        pass

    @classmethod
    def _get_max_output_width(cls) -> int:
        return (
            shutil.get_terminal_size((80, 20)).columns
            - len(cls.PADDING_LEFT)
            - len(cls.PADDING_RIGHT)
        )

    def _output(self, text: str | Text, pad: bool = True, **kwargs) -> None:
        # Convert text to Text object if it's a string
        if isinstance(text, str):
            text = Text(text)

        # Apply current indentation
        indented_text = Text(self._current_indent) + text

        self.output_console.print(
            (self.PADDING_LEFT if pad else Text(""))
            + indented_text
            + (self.PADDING_RIGHT if pad else Text("")),
            **kwargs,
        )


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
                    HTML(f"{self.PADDING_LEFT}<prompt>{prompt}</prompt>{self.PADDING_RIGHT}"),
                    style=self._input_style,
                    bottom_toolbar=toolbar_text,
                    multiline=multiline,
                    **kwargs
                )
            return result
        except KeyboardInterrupt:
            raise

    # SolveigInterface implementation
    def display_text(self, text: str, style: str = "") -> None:
        """Display text with optional styling."""
        style = style or self.color_palette.text
        self._output(Text(text, style=style))

    def display_error(self, error: str | Exception) -> None:
        """Display an error message with standard formatting."""
        self.display_text(f"❌ Error: {error}", style=self.color_palette.error)

    def display_warning(self, warning: str) -> None:
        """Display a warning message with standard formatting."""
        self.display_text(f"⚠️  Warning: {warning}", style=self.color_palette.warning)

    def display_success(self, message: str) -> None:
        """Display a success message with standard formatting."""
        self.display_text(f"✅ {message}")

    def display_comment(self, message: str) -> None:
        """Display a comment message."""
        self.display_text(message)

    def display_tree(
        self,
        metadata: Metadata,
        title: str | None = None,
        display_metadata: bool = False,
    ) -> None:
        tree_lines = self._get_tree_element_str(metadata, display_metadata)
        self.display_text_block(
            "\n".join(tree_lines),
            title=title or str(metadata.path),
        )

    @classmethod
    def _get_tree_element_str(
        cls, metadata: Metadata, display_metadata: bool = False, indent="  "
    ) -> list[str]:
        line = f"{'🗁 ' if metadata.is_directory else '🗎'} {metadata.path.name}"
        if display_metadata:
            if not metadata.is_directory:
                size_str = solveig.utils.misc.convert_size_to_human_readable(
                    metadata.size
                )
                line = f"{line}  |  size: {size_str}"
            modified_time = datetime.fromtimestamp(
                float(metadata.modified_time)
            ).isoformat()
            line = f"{line}  |  modified: {modified_time}"
        lines = [line]

        if metadata.is_directory and metadata.listing:
            for index, (_sub_path, sub_metadata) in enumerate(
                sorted(metadata.listing.items())
            ):
                is_last = index == len(metadata.listing) - 1
                entry_lines = cls._get_tree_element_str(sub_metadata, display_metadata, indent)

                # ├─🗁 d1
                lines.append(
                    f"{indent}{cls.TEXT_BOX.BL if is_last else cls.TEXT_BOX.VR}{cls.TEXT_BOX.H}{entry_lines[0]}"
                )

                # │  ├─🗁 sub-d1
                # │  └─🗎 sub-f1
                for sub_entry in entry_lines[1:]:
                    lines.append(
                        f"{indent}{'' if is_last else cls.TEXT_BOX.V}{sub_entry}"
                    )

        return lines

    def display_text_block(self, text: str, title: str = None) -> None:
        """Display a text block with optional title."""
        rendered_lines = self._render_text_box(
            text=text,
            title=title,
            max_width=self._get_max_output_width(),
            box_style=self.color_palette.box,
            text_style=self.color_palette.text
        )

        for line in rendered_lines:
            self._output(line)

    @classmethod
    def _render_text_box(
        cls,
        text: str,
        title: str = None,
        max_width: int = 80,
        box_style: str = "",
        text_style: str = ""
    ) -> list[Text]:
        """Render a text box with optional title. Returns list of Text objects to display."""
        lines = []

        # Top bar
        top_bar = Text(f"{cls.TEXT_BOX.TL}", style=box_style)
        if title:
            top_bar.append(f"{cls.TEXT_BOX.H * 3}")
            top_bar.append(f" {title} ", style=f"bold {box_style}")
        top_bar.append(
            f"{cls.TEXT_BOX.H * (max_width - len(top_bar) - 2)}{cls.TEXT_BOX.TR}"
        )
        lines.append(top_bar)

        # Content lines
        vertical_bar_left = Text(f"{cls.TEXT_BOX.V} ", style=box_style)
        vertical_bar_right = Text(f" {cls.TEXT_BOX.V} ", style=box_style)
        max_line_length = max_width - len(vertical_bar_left) - len(vertical_bar_right)

        content_lines = text.splitlines()
        for line in content_lines:
            if len(line) > max_line_length:
                truncated_line = f"{line[0:max_line_length - 3]}..."
            else:
                truncated_line = f"{line}{' ' * (max_line_length - len(line))}"
            line_text = Text(truncated_line, style=text_style)
            lines.append(vertical_bar_left + line_text + vertical_bar_right)

        # Bottom bar
        bottom_bar = Text(
            f"{cls.TEXT_BOX.BL}{cls.TEXT_BOX.H * (max_width - 3)}{cls.TEXT_BOX.BR}",
            style=box_style
        )
        lines.append(bottom_bar)

        return lines

    async def ask_user(self, prompt: str, placeholder: str = None, multiline: bool = False) -> str:
        """Ask for specific input with optional multi-line support."""
        if multiline:
            full_prompt = f"{prompt}: "
            self.display_text("📝 Multi-line input mode enabled. Use Alt+Enter for new lines.", style=self.color_palette.prompt)
        else:
            full_prompt = f"{prompt}: "
        return await self._input(full_prompt, multiline=multiline)

    async def get_input(self) -> str:
        """Get user input for conversation flow."""
        return await self._input(self.DEFAULT_INPUT_PROMPT)

    async def ask_yes_no(self, question: str, yes_values=None) -> bool:
        """Ask a yes/no question."""
        yes_values = yes_values or self.YES
        response = await self.ask_user(question, f"❓ {question} [y/N]")
        result = response.lower().strip() in yes_values
        # self.display_text(f"❓ {question} → {'Yes' if result else 'No'}", style=self.color_palette.prompt)
        return result

    def set_status(self, status: str) -> None:
        """Update status display (if supported)."""
        self.display_text(f"Status: {status}")

    async def start(self) -> None:
        """Start the interface lifecycle and block until stopped."""
        self._stop_event.clear()
        await self._stop_event.wait()

    async def stop(self) -> None:
        """Signal the interface lifecycle to stop, unblocking start()."""
        self._stop_event.set()

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
            style=f"bold {self.color_palette.section}",
            pad=False,
        )

    @contextmanager
    def with_group(self, title: str):
        """Context manager for grouping related output."""
        self.display_text(f"[ {title} ]", style=self.color_palette.group)

        # Increase indentation
        self._current_indent += " " * self.indent_base

        try:
            yield
        finally:
            # Decrease indentation
            self._current_indent = self._current_indent[:-self.indent_base]

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


