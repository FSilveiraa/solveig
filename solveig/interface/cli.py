"""
CLI implementation of Solveig interface.
"""

import shutil
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any

from .base import SolveigInterface


class CLIInterface(SolveigInterface):
    """Command-line interface implementation."""

    DEFAULT_INPUT_PROMPT = "Reply:\n > "

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

    def _output(self, text: str) -> None:
        print(text)

    def _input(self, prompt: str) -> str:
        return input(prompt)

    def _get_max_output_width(self) -> int:
        return shutil.get_terminal_size((80, 20)).columns

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
        self._output(f"\n{title_formatted}{padding}")

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
                            requirement.display_header(
                                None, self
                            )  # config not needed for LLM response display

    # display_requirement removed - requirements now display themselves directly

    def display_error(self, message: str | Exception) -> None:
        _exception = message
        if isinstance(_exception, Exception):
            message = str(f"{_exception.__class__.__name__}: {_exception}")
        super().display_error(message)
        if isinstance(_exception, Exception):
            traceback_block = "".join(
                traceback.format_exception(
                    type(_exception), _exception, _exception.__traceback__
                )
            )
            self.display_text_block(traceback_block, title="Error")

    def display_tree(
        self,
        metadata: dict[str, Any],
        listing: list[dict[str, Any]],
        level: int | None = None,
        max_lines: int | None = None,
        title: str | None = "Metadata",
    ) -> None:
        text = f"{'🗁' if metadata['is_directory'] else '🗎'} {metadata["path"]} | "
        # size for directories is visual noise
        if metadata["is_directory"]:
            metadata.pop("size")
        text += " | ".join([f"{key}={value}" for key, value in metadata.items()])
        # print("DEBUG: " + str(len(entries)) + " entries: " + str(entries))
        if listing:
            # text = f"{text}\nEntries:"
            total_entries = len(listing)
            for n, entry in enumerate(listing):
                entry_str = f"{'🗁' if entry['is_directory'] else '🗎'} {Path(entry["path"]).name}"
                # └ if it's the last item, otherwise ├
                text = f"{text}\n{self.TEXT_BOX.BL if n == (total_entries - 1) else self.TEXT_BOX.VR}{self.TEXT_BOX.H}{entry_str}"
        self.display_text_block(text, title=title, level=level, max_lines=max_lines)

    def display_text_block(
        self,
        text: str,
        title: str | None = None,
        level: int | None = None,
        max_lines: int | None = None,
    ) -> None:
        if not self.max_lines or not text:
            return

        indent = self._indent(level)
        max_width = self._get_max_output_width()

        # ┌─── Content ─────────────────────────────┐
        top_bar = f"{indent}{self.TEXT_BOX.TL}"
        if title:
            top_bar = f"{top_bar}{self.TEXT_BOX.H * 3} {title.title()} "
        self._output(
            f"{top_bar}{self.TEXT_BOX.H * (max_width - len(top_bar) - 1)}{self.TEXT_BOX.TR}"
        )

        vertical_bar_left = f"{indent}{self.TEXT_BOX.V} "
        vertical_bar_right = f" {self.TEXT_BOX.V}"
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
                self._output(f"{vertical_bar_left}{truncated_line}{vertical_bar_right}")
                # self._output(f"{vertical_bar_left}...{' ' * (max_line_length-3)}{vertical_bar_right}")
                break

            # truncate individual line length
            # truncated_line = line[0:max_line_length]
            if len(line) > max_line_length:
                # _before = truncated_line
                truncated_line = f"{line[0:max_line_length - 3]}..."
            else:
                truncated_line = f"{line}{' ' * (max_line_length - len(line))}"
            # print(f"DEBUG: truncated line: {line} -> {truncated_line}")
            self._output(f"{vertical_bar_left}{truncated_line}{vertical_bar_right}")

        # └─────────────────────────────────────────┘
        self._output(
            f"{indent}{self.TEXT_BOX.BL}{self.TEXT_BOX.H * (max_width - len(indent) - 2)}{self.TEXT_BOX.BR}"
        )
