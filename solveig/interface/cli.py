"""
CLI implementation of Solveig interface.
"""

from collections import defaultdict
import shutil

from ..utils import misc
from .base import RequirementPresentation, SolveigInterface


DEFAULT_INPUT_PROMPT = "Reply:\n > "
DEFAULT_YES = { "y", "yes" }


class CLIInterface(SolveigInterface):
    """Command-line interface implementation."""

    def _output(self, text: str) -> None:
        print(text)

    def _get_max_output_width(self) -> int:
        return shutil.get_terminal_size((80, 20)).columns

    def display_section_header(self, title: str) -> None:
        """Display a section header using the existing print_line utility."""
        misc.print_line(title)

    def display_llm_response(self, llm_response: "LLMMessage") -> None:
        """Display the LLM response and requirements summary."""
        self.display_section_header("Assistant")
        if llm_response.comment:
            self.show(f"❝ {llm_response.comment.strip()}")

        if llm_response.requirements:
            with self.group("[ Requirements ({len(message.requirements)}) ]"):
                indexed_requirements = defaultdict(list)
                for requirement in llm_response.requirements:
                    indexed_requirements[requirement.title].append(requirement)

                for requirement_type, requirements in indexed_requirements.items():
                    with self.group(f"[{requirement_type.title()}]"):
                        for requirement in requirements:
                            requirement_presentation = requirement.get_presentation_data()
                            if requirement_presentation.details:
                                self.show(requirement_presentation.details)

    def display_requirement(self, presentation: RequirementPresentation) -> None:
        """Display a single requirement with proper formatting."""
        with self.group(f"{presentation.title}"):
            self.show(f"❝ {presentation.comment}")

            # Display details (path info, etc.)
            for detail in presentation.details:
                self.show(detail)

            # Display warnings if any
            if presentation.warnings:
                for warning in presentation.warnings:
                    self.show(f"⚠ {warning}")

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

    def display_requirements_header(self, count: int) -> None:
        """Display header for requirements section."""
        self.show(f"[ Requirements ({count}) ]")

    def display_results_header(self, count: int) -> None:
        """Display header for requirement results section."""
        self.display_section_header("User")
        self.show(f"[ Requirement Results ({count}) ]")

    def display_error(self, message: str) -> None:
        """Display an error message with proper formatting."""
        self.show(f"{message}")

    # def display_status(self, message: str) -> None:
    #     """Display a status message."""
    #     self.show(message)

    def ask_user(self, prompt: str = DEFAULT_INPUT_PROMPT) -> str:
        """Get text input from user."""
        return input(prompt).strip()

    # def ask_yes_no(self, prompt: str) -> bool:
    #     """Ask user a yes/no question."""
    #     return misc.ask_yes(prompt)

    def display_verbose_info(self, message: str) -> None:
        """Display verbose information only if verbose mode is enabled."""
        if self.be_verbose:
            self.show(message)

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
