"""
CLI implementation of Solveig interface.
"""

from typing import TYPE_CHECKING

from ..utils import misc
from .base import RequirementPresentation, SolveigInterface

if TYPE_CHECKING:
    from ..config import SolveigConfig
    from ..schema.message import LLMMessage


class CLIInterface(SolveigInterface):
    """Command-line interface implementation."""

    def __init__(self, config: "SolveigConfig"):
        self.config = config

    def display_section_header(self, title: str) -> None:
        """Display a section header using the existing print_line utility."""
        misc.print_line(title)

    def display_llm_response(self, llm_response: "LLMMessage") -> None:
        """Display the LLM response and requirements summary."""
        self.display_section_header("Assistant")
        if llm_response.comment:
            print(f"❝ {llm_response.comment.strip()}")

        if llm_response.requirements:
            print(f"\n[ Requirements ({len(llm_response.requirements)}) ]")
            self._summarize_requirements(llm_response)

    def display_requirement(self, presentation: RequirementPresentation) -> None:
        """Display a single requirement with proper formatting."""
        print(f"  [ {presentation.title} ]")
        print(f"    ❝ {presentation.comment}")

        # Display details (path info, etc.)
        for detail in presentation.details:
            print(detail)

        # Display warnings if any
        if presentation.warnings:
            for warning in presentation.warnings:
                print(f"    {warning}")

        # Display content preview if any
        if presentation.content_preview:
            print("      [ Content ]")
            formatted_content = misc.format_output(
                presentation.content_preview,
                indent=8,
                max_lines=self.config.max_output_lines,
                max_chars=self.config.max_output_size,
            )
            print(formatted_content)

    def display_requirements_header(self, count: int) -> None:
        """Display header for requirements section."""
        print(f"[ Requirements ({count}) ]")

    def display_results_header(self, count: int) -> None:
        """Display header for requirement results section."""
        self.display_section_header("User")
        print(f"[ Requirement Results ({count}) ]")

    def display_error(self, message: str) -> None:
        """Display an error message with proper formatting."""
        print(f"  {message}")

    def display_status(self, message: str) -> None:
        """Display a status message."""
        print(message)

    def prompt_user(self, prompt: str | None = None) -> str:
        """Get text input from user using existing utility."""
        if prompt is None:
            prompt = misc.INPUT_PROMPT
        return misc.prompt_user(prompt)

    def ask_yes_no(self, prompt: str) -> bool:
        """Ask user a yes/no question using existing utility."""
        return misc.ask_yes(prompt)

    def display_verbose_info(self, message: str) -> None:
        """Display verbose information only if verbose mode is enabled."""
        if self.config.verbose:
            print(message)

    def _summarize_requirements(self, message: "LLMMessage") -> None:
        """Display requirements summary (preserves existing logic from solveig_cli.py)."""
        from ..schema.requirement import (
            CommandRequirement,
            CopyRequirement,
            DeleteRequirement,
            MoveRequirement,
            ReadRequirement,
            WriteRequirement,
        )

        reads, writes, commands, moves, copies, deletes = [], [], [], [], [], []
        for requirement in message.requirements or []:
            if isinstance(requirement, ReadRequirement):
                reads.append(requirement)
            elif isinstance(requirement, WriteRequirement):
                writes.append(requirement)
            elif isinstance(requirement, CommandRequirement):
                commands.append(requirement)
            elif isinstance(requirement, MoveRequirement):
                moves.append(requirement)
            elif isinstance(requirement, CopyRequirement):
                copies.append(requirement)
            elif isinstance(requirement, DeleteRequirement):
                deletes.append(requirement)

        if reads:
            print("  Read:")
            for requirement in reads:
                print(
                    f"    {requirement.path} ({'metadata' if requirement.only_read_metadata else 'content'})"
                )

        if writes:
            print("  Write:")
            for requirement in writes:
                print(f"    {requirement.path}")

        if moves:
            print("  Move:")
            for requirement in moves:
                print(f"    {requirement.source_path} → {requirement.destination_path}")

        if copies:
            print("  Copy:")
            for requirement in copies:
                print(f"    {requirement.source_path} → {requirement.destination_path}")

        if deletes:
            print("  Delete:")
            for requirement in deletes:
                print(f"    {requirement.path}")

        if commands:
            print("  Commands:")
            for requirement in commands:
                print(f"    {requirement.command}")
