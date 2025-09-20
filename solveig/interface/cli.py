"""
CLI implementation of Solveig interface.
"""

import shutil
import sys
import random
import traceback
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any, Generator

import solveig.utils.misc
from solveig.interface.base import SolveigInterface
from solveig.utils.file import Metadata
from rich.console import Console, Text

if TYPE_CHECKING:
    from solveig.schema import LLMMessage


class CLIInterface(SolveigInterface):
    """Command-line interface implementation."""

    DEFAULT_INPUT_PROMPT = "Reply:\n > "
    PADDING_LEFT = Text(" ")
    PADDING_RIGHT = Text(" ")

    class TEXT_BOX:
        # Basic
        H = "─"
        V = "│"
        # Corners
        TL = "┌"  # top-left
        TR = "┐"  # top-right
        BL = "└"  # bottom-left
        BR = "┘"  # bottom-right
        # Junctions
        VL = "┤"
        VR = "├"
        HB = "┬"
        HT = "┴"
        # Cross
        X = "┼"

    class COLORS:
        title = "thistle3"
        group = "dark_sea_green"
        error = "red"
        warning = "orange3"
        text_block = "grey93"

    def __init__(self, animation_interval: float = 0.1, **kwargs) -> None:
        super().__init__(**kwargs)
        self.animation_interval = animation_interval
        self.console = Console()

    def _output(self, text: str | Text, **kwargs) -> None:
        # Use rich console for all output to get color support
        # self.console.print(f"{self.PADDING_LEFT}{text}{self.PADDING_RIGHT}")
        self.console.print(self.PADDING_LEFT + text + self.PADDING_RIGHT, **kwargs)

    def _output_inline(self, text: str) -> None:
        sys.stdout.write(f"\r{self.PADDING_LEFT}{text}{self.PADDING_RIGHT}")
        sys.stdout.flush()

    def _input(self, prompt: str, **kwargs) -> str:
        user_input = input(f"{self.PADDING_LEFT}{prompt}{self.PADDING_RIGHT}")
        return user_input

    def _get_max_output_width(self) -> int:
        return shutil.get_terminal_size((80, 20)).columns - len(self.PADDING_LEFT) - len(self.PADDING_RIGHT)

    @contextmanager
    def with_group(
        self, title: str, count: int | None = None
    ) -> Generator[None, None, None]:
        """
        Group/item header with optional count
        [ Requirements (3) ]
        """
        count_str = f" ({count})" if count is not None else ""
        self.show(f"{title}{count_str}", style=f"bold {self.COLORS.group}")
        # self.show(f"[ {title}{count_str} ]", style=f"bold {self.COLORS.group}")

        # Use the with_indent context manager internally
        with self.with_indent():
            yield

    def display_section(self, title: str) -> None:
        """
        Section header with line
        ─── User ───────────────
        """
        terminal_width = self._get_max_output_width()
        title_formatted = f"{self.TEXT_BOX.H * 3} {title} " if title else ""
        padding = (
            self.TEXT_BOX.H * (terminal_width - len(title_formatted))
            if terminal_width > 0
            else ""
        )
        self._output(f"\n\n{title_formatted}{padding}", style=f"bold {self.COLORS.warning}")

    def display_llm_response(self, llm_response: "LLMMessage") -> None:
        """Display the LLM response and requirements summary."""
        if llm_response.comment:
            self.display_comment(llm_response.comment.strip())

        if llm_response.requirements:
            with self.with_group("Requirements", len(llm_response.requirements)):
                indexed_requirements = defaultdict(list)
                for requirement in llm_response.requirements:
                    indexed_requirements[requirement.title].append(requirement)

                for requirement_type, requirements in indexed_requirements.items():
                    with self.with_group(
                        requirement_type.title(), count=len(requirements)
                    ):
                        for requirement in requirements:
                            requirement.display_header(interface=self)

    # display_requirement removed - requirements now display themselves directly

    def display_tree(
        self,
        metadata: Metadata,
        level: int | None = None,
        max_lines: int | None = None,
        title: str | None = None,
        display_metadata: bool = False,
    ) -> None:
        self.display_text_block(
            "\n".join(self._get_tree_element_str(metadata, display_metadata)),
            title=title or str(metadata.path),
            level=level,
            max_lines=max_lines,
        )

    def _get_tree_element_str(
        self, metadata: Metadata, display_metadata: bool = False, indent="  "
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
                entry_lines = self._get_tree_element_str(sub_metadata, indent=indent)

                # ├─🗁 d1                                                                                                                │
                lines.append(
                    f"{indent}{self.TEXT_BOX.BL if is_last else self.TEXT_BOX.VR}{self.TEXT_BOX.H}{entry_lines[0]}"
                )

                # │  ├─🗁 sub-d1
                # │  └─🗎 sub-f1
                for sub_entry in entry_lines[1:]:
                    lines.append(
                        f"{indent}{'' if is_last else self.TEXT_BOX.V}{sub_entry}"
                    )

        return lines

    def display_text_block(
        self,
        text: str,
        title: str | None = None,
        level: int | None = None,
        max_lines: int | None = None,
        box_style: str = COLORS.title,
        text_style: str | None = COLORS.text_block,
    ) -> None:
        if not self.max_lines or not text:
            return

        indent = self._indent(level)
        max_width = self._get_max_output_width()

        # ┌─── Content ─────────────────────────────┐
        top_bar = Text(f"{indent}{self.TEXT_BOX.TL}", style=box_style)
        if title:
            top_bar.append(f"{self.TEXT_BOX.H * 3}")
            top_bar.append(f" {title} ", style=f"bold {box_style}")
        top_bar.append(f"{self.TEXT_BOX.H * (max_width - len(top_bar) - 2)}{self.TEXT_BOX.TR}")
        self._output(top_bar)
        #     f"{top_bar}{self.TEXT_BOX.H * (max_width - len(top_bar) - 2)}{self.TEXT_BOX.TR} "
        # )

        vertical_bar_left = Text(f"{indent}{self.TEXT_BOX.V} ", style=box_style)
        vertical_bar_right = Text(f" {self.TEXT_BOX.V} ", style=box_style)
        max_line_length = (
            self._get_max_output_width()
            - len(vertical_bar_left)
            - len(vertical_bar_right)
        )

        lines = text.splitlines()
        for line_no, line in enumerate(lines):
            # truncate number of lines
            if line_no == self.max_lines:
                lines_missing = len(lines) - line_no
                truncated_line = f" ({lines_missing} more...)"
                truncated_line = (
                    f"{truncated_line}{' ' * (max_line_length - len(truncated_line))}"
                )
                line_text = Text(truncated_line)
                self._output(vertical_bar_left + line_text + vertical_bar_right)
                break

            if len(line) > max_line_length:
                truncated_line = f"{line[0:max_line_length - 3]}..."
            else:
                truncated_line = f"{line}{' ' * (max_line_length - len(line))}"
            line_text = Text(truncated_line, style=text_style)
            self._output(vertical_bar_left + line_text + vertical_bar_right)

        # └─────────────────────────────────────────┘
        self._output(
            f"{indent}{self.TEXT_BOX.BL}{self.TEXT_BOX.H * (max_width - len(indent) - 3)}{self.TEXT_BOX.BR} ",
            style=box_style,
        )

    def display_animation_while(
        self, run_this: Callable, message: str | None = None, animation_type: str | None = None
    ) -> Any:
        animation = Animation(animation_type=animation_type)
        return animation.animate_while(self, run_this, message)

    def display_warning(self, message: str) -> None:
        """Override to add orange color for CLI warnings."""
        self.show(f"⚠  {message}", style=self.COLORS.warning)
        # indent = self._indent()
        # self.console.print(f"{self.PADDING_LEFT}{indent}⚠  {message}{self.PADDING_RIGHT}", style="orange3")

    def display_error(
        self, message: str | Exception | None = None, exception: Exception | None = None
    ) -> None:
        """Override to add red color for CLI errors."""
        # Handle the error formatting logic from base class
        if not exception and not message:
            raise RuntimeError("Need to specify message or exception")
        if isinstance(message, Exception) and not exception:
            exception = message
            message = ""
        message = message or str(f"{exception.__class__.__name__}: {exception}")
        
        # Display with red color
        indent = self._indent()
        self.show(f"✖  {message}", style=self.COLORS.error)
        # self.console.print(f"{self.PADDING_LEFT}{indent}✖  {message}{self.PADDING_RIGHT}", style="red")
        
        # Handle verbose traceback
        if exception and self.verbose:
            traceback_block = "".join(
                traceback.format_exception(
                    type(exception), exception, exception.__traceback__
                )
            )
            self.display_text_block(traceback_block, title=exception.__class__.__name__, box_style=self.COLORS.error)


class Animation:
    SPINNERS = {
        "spin": ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
        "bounce": ["⠁", "⠂", "⠄", "⠂"],
        "dots": ["․", "⁚", "⁖", "⁘", "⁙", "⁜", "⁙", "⁘", "⁖", "⁚"],
        # "moon_color": ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"],
        "moon": ["◯", "☽", "◑", "●", "◐", "❨"],
        "growing": ["🤆", "🤅", "🤄", "🤃", "🤄", "🤅", "🤆"],
        "cool": ["⨭", "⨴", "⨂", "⦻", "⨂", "⨵", "⨮", "⨁"],
    }

    def __init__(
        self,
        animation_type: str | None = None,
        frames: list[str] | None = None,
        interval: float = 0.2,
    ):
        """
        Initialize spinner.

        Args:
            animation_type: Type of animation to use (None=random).
            frames: List of icon frames to cycle through
            interval: Time between frame changes in seconds
        """
        self.frames = frames or self.SPINNERS[animation_type or random.choice(list(self.SPINNERS.keys()))]
        self.interval = interval
        self._current_frame = 0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _animate(self, interface: CLIInterface, message: str | None = None) -> None:
        """Run the animation loop."""
        while not self._stop_event.is_set():
            # Show current frame with message
            frame = self.frames[self._current_frame]
            display_text = f"{frame}  {message}" if message else frame
            interface._output_inline(display_text)

            # Advance to next frame
            self._current_frame = (self._current_frame + 1) % len(self.frames)

            # Wait for next frame, but check for stop event
            if self._stop_event.wait(self.interval):
                break

    def animate_while(
        self,
        interface: CLIInterface,
        run_this: Callable,
        message: str | None = None,
    ) -> Any:
        """
        Run a blocking function while showing an animated spinner.

        Args:
            interface: The CLIInterface instance to use for displaying information
            run_this: Function to run while animation plays
            message: Message to show with spinner

        Returns:
            Result from the blocking function
        """
        # Start spinner in background thread
        self._thread = threading.Thread(
            target=self._animate, 
            args=(interface, message or "Waiting... (Ctrl+C to stop)"),
            daemon=True
        )
        self._thread.start()

        try:
            # Run the blocking function in the main thread
            result = run_this()
            return result
        finally:
            # Stop the animation
            self._stop_event.set()
            if self._thread:
                self._thread.join(timeout=0.5)  # Give it a moment to stop gracefully
            interface.show("")  # Clear the animation line
