"""
CLI implementation of Solveig interface.
"""

import random
import shutil
import traceback
from collections import defaultdict
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.output import ColorDepth
from rich.console import Console, Text

import solveig.utils.misc
from solveig.interface.base import SolveigInterface
from solveig.utils.file import Metadata

if TYPE_CHECKING:
    from solveig.schema.message import AssistantMessage

"""
Important compatibility note:
When using rich.Console for output and prompt_toolkit.PromptSession for input
Use prompt_toolkit.path_stdout.patch_stdout() for threads that call console.print() while a PromptSession is active.

from prompt_toolkit.patch_stdout import patch_stdout
with patch_stdout():
    with run_thread(output_console):
        text = session.prompt("?")
"""


class CLIInterface(SolveigInterface):
    """Command-line interface implementation."""

    DEFAULT_INPUT_PROMPT = ">"
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

    # https://rich.readthedocs.io/en/stable/appendix/colors.html
    class COLORS:
        # rich.console
        title = "rosy_brown"
        group = "dark_sea_green"
        error = "red"
        warning = "orange3"
        text_block = "reset"

    class COLORS_INPUT:
        title = "#bc8f8f"  # rosy_brown
        group = "#8fbc8f"  # dark_sea_green
        error = "#ff0000"  # red
        warning = "#ff8700"  # orange3
        text_block = "default"  # reset

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

    def __init__(self, animation_interval: float = 0.1, **kwargs) -> None:
        super().__init__(**kwargs)
        self.animation_interval = animation_interval
        self.output_console = Console()
        self.input_console: PromptSession = PromptSession(
            color_depth=ColorDepth.TRUE_COLOR
        )
        self._input_style_dict = self.theme.to_prompt_toolkit_style()
        if self.theme.background:
            self._output(
                Text(
                    f"The theme '{self.theme.name}' expects the following background color ({self.theme.background}): ",
                    style=self.theme.text,
                )
                + Text("𜴙𜵟███𜶆𜶀", style=self.theme.background)
            )

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
        # This is a hack: we take a str and convert it to a list[str]
        for spinner in self.ALLOWED_SPINNERS:
            frames = RICH_SPINNERS[spinner]["frames"]
            RICH_SPINNERS[spinner]["frames"] = [
                f"{self.PADDING_LEFT}{frame}" for frame in frames  # type: ignore
            ]

    def _get_max_output_width(self) -> int:
        return (
            shutil.get_terminal_size((80, 20)).columns
            - len(self.PADDING_LEFT)
            - len(self.PADDING_RIGHT)
        )

    def _output(self, text: str | Text, pad: bool = True, **kwargs) -> None:
        # Use rich console for all output to get color support
        self.output_console.print(
            (self.PADDING_LEFT if pad else Text(""))
            + text
            + (self.PADDING_RIGHT if pad else Text("")),
            **kwargs,
        )

    def _output_inline(self, text: str | Text, pad: bool = True) -> None:
        # Use Rich console for inline output
        self.output_console.print(
            (self.PADDING_LEFT if pad else Text(""))
            + text
            + (self.PADDING_RIGHT if pad else Text("")),
            end="",
        )
        # f"\r{self.PADDING_LEFT}{text}{self.PADDING_RIGHT}", end="")

    def _input(self, prompt: str, style: str | None = None, **kwargs) -> str:
        # style = style or self.theme.prompt
        return self.input_console.prompt(
            HTML(f"{self.PADDING_LEFT}<prompt>{prompt}</prompt>{self.PADDING_RIGHT}"),
            style=self._input_style_dict,
            **kwargs,
        )

    def ask_user(
        self, question: str = DEFAULT_INPUT_PROMPT, level: int | None = None, **kwargs
    ) -> str:
        """Ask user a question and get a response."""
        indent = self._indent(level)
        text = f"{indent}{question}"
        return self._input(text)

    def display_text(
        self,
        text: str,
        level: int | None = None,
        truncate: bool = False,
        style=None,
        **kwargs,
    ) -> None:
        indent = self._indent(level)
        text_formatted = f"{indent}{text}"
        style = style or self.theme.text
        if truncate:
            # We add this in either case - cut lines, cut length, or both
            _ellipsis = ""

            # Keep only the first line
            suffix = ""
            lines = text_formatted.splitlines()
            if len(lines) > 1:
                text_formatted = lines[0]
                suffix = f"(+{len(lines) - 1} lines)"
                # from here on we know we'll need it, but don't add it yet
                _ellipsis = " ..."

            # Shorten the line to the max possible width
            max_width = (
                self._get_max_output_width()
                - len(suffix)  # padding for " (+22 lines)" if necessary
                - 4  # padding for " ..." if necessary - even if it wasn't defined above
            )
            if len(text_formatted) > max_width:
                text_formatted = f"{text_formatted[:max_width]}"
                # if we didn't ... because of the lines, add because of the length
                _ellipsis = " ..."
            self._output(
                Text(text_formatted, style=style)
                .append(_ellipsis, style=self.theme.box)
                .append(suffix, style=self.theme.box),
                **kwargs,
            )
        else:
            self._output(Text(text_formatted, style=style), **kwargs)

    @contextmanager
    def with_group(self, title: str) -> Generator[None]:
        """
        Group/item header with optional count
        [ Requirements (3) ]
        """
        self.display_text(f"{title}", style=f"bold {self.theme.group}")

        # Use the with_indent context manager internally
        with self.with_indent():
            yield

    def display_section(self, title: str) -> None:
        """
        Section header with line
        ─── User ───────────────
        """
        # hack to get unpadded terminal width
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
            style=f"bold {self.theme.section}",
            pad=False,
        )

    def display_llm_response(self, llm_response: "AssistantMessage") -> None:
        """Display the LLM response and requirements summary."""
        if llm_response.comment:
            self.display_comment(llm_response.comment.strip())

        if llm_response.requirements:
            with self.with_group(f"Requirements ({len(llm_response.requirements)})"):
                indexed_requirements = defaultdict(list)
                for requirement in llm_response.requirements:
                    indexed_requirements[requirement.title].append(requirement)

                for requirement_type, requirements in indexed_requirements.items():
                    with self.with_group(
                        f"{requirement_type.title()} ({len(requirements)})"
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

                # ├─🗁 d1
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
        box_style: str | None = None,
        text_style: str | None = None,
    ) -> None:
        if not self.max_lines or not text:
            return

        indent = self._indent(level)
        max_width = self._get_max_output_width()

        box_style = box_style or self.theme.box
        text_style = text_style or self.theme.text

        # ┌─── Content ─────────────────────────────┐
        top_bar = Text(f"{indent}{self.TEXT_BOX.TL}", style=box_style)
        if title:
            top_bar.append(f"{self.TEXT_BOX.H * 3}")
            top_bar.append(f" {title} ", style=f"bold {box_style}")
        top_bar.append(
            f"{self.TEXT_BOX.H * (max_width - len(top_bar) - 2)}{self.TEXT_BOX.TR}"
        )
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
        self,
        run_this: Callable,
        message: str | None = None,
        animation_type: str | None = None,
        style: str | None = None,
    ) -> Any:
        style = style or self.theme.prompt

        # Pick random spinner if none specified
        if animation_type is None:
            animation_type = random.choice(list(self.ALLOWED_SPINNERS))

        # Assert the spinner is in our allowed set
        assert (
            animation_type in self.ALLOWED_SPINNERS
        ), f"Spinner '{animation_type}' not in allowed set: {self.ALLOWED_SPINNERS}"

        display_message = message or "Waiting... (Ctrl+C to stop)"

        # Use Rich status for styled animation that integrates with console
        with self.output_console.status(
            Text(
                f"{self.PADDING_LEFT}{display_message}{self.PADDING_RIGHT}", style=style
            ),
            spinner=animation_type,
            spinner_style=style,
        ):
            return run_this()

    def display_warning(self, message: str) -> None:
        """Override to add orange color for CLI warnings."""
        self.display_text(f"⚠  {message}", style=self.theme.warning)

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
        self.display_text(f"✖  {message}", style=self.theme.error)
        # self.console.print(f"{self.PADDING_LEFT}{indent}✖  {message}{self.PADDING_RIGHT}", style="red")

        # Handle verbose traceback
        if exception and self.verbose:
            traceback_block = "".join(
                traceback.format_exception(
                    type(exception), exception, exception.__traceback__
                )
            )
            self.display_text_block(
                traceback_block,
                title=exception.__class__.__name__,
                box_style=self.theme.error,
            )
