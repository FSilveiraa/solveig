"""
CLI implementation of Solveig interface.
"""

from collections import defaultdict
import shutil

# from ..utils import misc
from .base import RequirementPresentation, SolveigInterface


# DEFAULT_INPUT_PROMPT = "Reply:\n > "
# DEFAULT_YES = { "y", "yes" }


class CLIInterface(SolveigInterface):
    """Command-line interface implementation."""

    DEFAULT_INPUT_PROMPT = "Reply:\n > "

    class TEXT_BOX:
        H = "─"
        V = "│"
        TL = "┌"  # top-left
        TR = "┐"  # top-right
        BL = "└"  # bottom-left
        BR = "┘"  # bottom-right

    def _output(self, text: str) -> None:
        print(text)

    def _input(self, prompt: str) -> str:
        return input(prompt)

    def _get_max_output_width(self) -> int:
        return shutil.get_terminal_size((80, 20)).columns

    # def display_section_header(self, title: str) -> None:
    #     """Display a section header using the existing print_line utility."""
    #     misc.print_line(title)

    def display_section(self, title: str) -> None:
        """
        Section header with line
        --- User ---------------
        """
        terminal_width = self._get_max_output_width()
        title_formatted = f"{self.TEXT_BOX.H * 3} {title} " if title else ""
        padding = self.TEXT_BOX.H * (terminal_width - len(title_formatted)) if terminal_width > 0 else ""
        self._output(f"\n{title_formatted}{padding}")

    def display_llm_response(self, llm_response: "LLMMessage") -> None:
        """Display the LLM response and requirements summary."""
        if llm_response.comment:
            self.display_comment(llm_response.comment.strip())

        if llm_response.requirements:
            with self.group("Requirements", len(llm_response.requirements)):
                indexed_requirements = defaultdict(list)
                for requirement in llm_response.requirements:
                    indexed_requirements[requirement.title].append(requirement)

                for requirement_type, requirements in indexed_requirements.items():
                    with self.group(requirement_type.title()):
                        for requirement in requirements:
                            requirement_presentation = requirement.get_presentation_data()
                            if requirement_presentation.details:
                                for requirement_info in requirement_presentation.details:
                                    self.show(requirement_info)
                            if requirement_presentation.warnings:
                                for warning in requirement_presentation.warnings:
                                    self.display_warning(warning)

    def display_requirement(self, presentation: RequirementPresentation) -> None:
        """Display a single requirement with proper formatting."""
        self.display_comment(presentation.comment)

        # Display details (path info, etc.)
        for detail in presentation.details:
            self.show(detail)

        # Display warnings if any
        if presentation.warnings:
            for warning in presentation.warnings:
                self.display_warning(warning)

        # Display content preview if any
        if presentation.content:
            with self.group("Content"):
                # formatted_content = misc.format_output(
                #     presentation.content_preview,
                #     indent=8,
                #     max_lines=-1, #self.config.max_output_lines,
                #     max_chars=-1, #self.config.max_output_size,
                # )
                self.show(presentation.content)

    # def display_requirements_header(self, count: int) -> None:
    #     """Display header for requirements section."""
    #     self.show(f"[ Requirements ({count}) ]")

    # def display_results_header(self, count: int) -> None:
    #     """Display header for requirement results section."""
    #     self.section("")
    #     self.display_section_header("User")
    #     self.show(f"[ Requirement Results ({count}) ]")

    # def display_error(self, message: str) -> None:
    #     """Display an error message with proper formatting."""
    #     self.show(f"{message}")

    # def display_status(self, message: str) -> None:
    #     """Display a status message."""
    #     self.show(message)

    # def ask_user(self, prompt: str = DEFAULT_INPUT_PROMPT, auto_format = True) -> str:
    #     """Get text input from user."""
    #     return super().ask_user(prompt, auto_format=auto_format)

    # def ask_yes_no(self, prompt: str) -> bool:
    #     """Ask user a yes/no question."""
    #     return misc.ask_yes(prompt)

    # def display_verbose_info(self, message: str) -> None:
    #     """Display verbose information only if verbose mode is enabled."""
    #     if self.be_verbose:
    #         self.show(message)

    # def _summarize_requirements(self, message: "LLMMessage") -> None:
    #     """Display requirements summary (preserves existing logic from solveig_cli.py)."""
    #     # from ..schema.requirement import (
    #     #     CommandRequirement,
    #     #     CopyRequirement,
    #     #     DeleteRequirement,
    #     #     MoveRequirement,
    #     #     ReadRequirement,
    #     #     WriteRequirement,
    #     # )
    #
    #     with self.group("[ Requirements ({len(message.requirements)}) ]"):
    #         indexed_requirements = defaultdict(list)
    #         for requirement in message.requirements:
    #             indexed_requirements[requirement.title].append(requirement)
    #
    #         for requirement_type, requirements in indexed_requirements.items():
    #             with self.group(f"[{requirement_type.title()}]"):
    #                 for requirement in requirements:
    #                     requirement_presentation = requirement.get_presentation_data()
    #                     if requirement_presentation.details:
    #                         self.show(requirement_presentation.details)


        # if reads:
        #     print("  Read:")
        #     for requirement in reads:
        #         print(
        #             f"    {requirement.path} ({'metadata' if requirement.only_read_metadata else 'content'})"
        #         )
        #
        # if writes:
        #     print("  Write:")
        #     for requirement in writes:
        #         print(f"    {requirement.path}")
        #
        # if moves:
        #     print("  Move:")
        #     for requirement in moves:
        #         print(f"    {requirement.source_path} → {requirement.destination_path}")
        #
        # if copies:
        #     print("  Copy:")
        #     for requirement in copies:
        #         print(f"    {requirement.source_path} → {requirement.destination_path}")
        #
        # if deletes:
        #     print("  Delete:")
        #     for requirement in deletes:
        #         print(f"    {requirement.path}")
        #
        # if commands:
        #     print("  Commands:")
        #     for requirement in commands:
        #         print(f"    {requirement.command}")



    def display_text_block(self, text: str, title: str | None = None, level: int | None = None, max_lines: int | None = None) -> None:
        if not self.max_lines or not text:
            return

        indent = self._indent(level)
        max_width = self._get_max_output_width()

        # ┌─── Content ─────────────────────────────┐
        top_bar = f"{indent}{self.TEXT_BOX.TL}"
        if title:
            top_bar = f"{top_bar}{self.TEXT_BOX.H * 3} {title.title()} "
        self._output(f"{top_bar}{self.TEXT_BOX.H * (max_width - len(top_bar) - 1)}{self.TEXT_BOX.TR}")

        vertical_bar_left = f"{indent}{self.TEXT_BOX.V} "
        vertical_bar_right = f" {self.TEXT_BOX.V}"
        max_line_length = self._get_max_output_width() - len(vertical_bar_left) - len(vertical_bar_right)

        current_line_no = 0
        for line in text.splitlines():
            current_line_no += 1
            if current_line_no > self.max_lines:
                # self._output(f"{vertical_bar_left}...{' ' * (max_line_length-3)}{vertical_bar_right}")
                break
            truncated_line = line[0:max_line_length]
            if len(truncated_line) > max_line_length:
                truncated_line = f"{truncated_line[0:max_line_length - 3]}..."
            else:
                truncated_line = f"{truncated_line}{' ' * (max_line_length - len(truncated_line))}"
            self._output(f"{vertical_bar_left}{truncated_line}{vertical_bar_right}")

        # └─────────────────────────────────────────┘
        self._output(f"{indent}{self.TEXT_BOX.BL}{self.TEXT_BOX.H * (max_width - len(indent) - 2)}{self.TEXT_BOX.BR}")
