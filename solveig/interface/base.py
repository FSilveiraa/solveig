"""
Base interface classes for Solveig user interaction.
"""
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generator, Optional

from .. import SolveigConfig

if TYPE_CHECKING:
    from ..schema.message import LLMMessage




@dataclass
class RequirementPresentation:
    """Data structure containing everything needed to display a requirement."""
    title: str
    comment: str
    details: list[str]
    warnings: list[str] | None = None
    content: str | None = None


class SolveigInterface(ABC):
    """Abstract base class for all Solveig user interfaces."""

    DEFAULT_INPUT_PROMPT = "> "
    DEFAULT_YES = {"y", "yes"}

    
    def __init__(self, indent_base: int = 2, max_lines = 6, be_verbose: bool = False):
        self.indent_base = indent_base
        self.current_level = 0
        self.max_lines = max_lines
        self.be_verbose = be_verbose

    # Implement these:

    @abstractmethod
    def _output(self, text: str) -> None:
        """Raw output method - implemented by concrete interfaces"""
        pass

    @abstractmethod
    def _input(self, prompt: str) -> str:
        """Get text input from user."""
        pass
    
    @abstractmethod
    def _get_max_output_width(self) -> int:
        """Get terminal width - implemented by concrete interfaces (-1 to disable)"""
        pass

    @abstractmethod
    def display_llm_response(self, llm_response: "LLMMessage") -> None:
        """Display the LLM's comment and requirements summary."""
        pass

    @abstractmethod
    def display_requirement(self, presentation: RequirementPresentation) -> None:
        """Display a single requirement with its presentation data."""
        pass

    @abstractmethod
    def display_text_block(self, text: str, title: str | None = None, level: int | None = None, max_lines: int | None = None) -> None:
        """Display a block of text."""
        pass

    #####
    
    def _indent(self, level: Optional[int] = None) -> str:
        """Calculate indentation for given level (or current level)"""
        actual_level = level if level is not None else self.current_level
        return " " * (actual_level * self.indent_base)
    
    def show(self, content: str, level: Optional[int] = None) -> None:
        """Display content at specified or current indent level"""
        indent = self._indent(level)
        self._output(f"{indent}{content}")

    def display_section(self, title: str) -> None:
        """
        Section header with line
        --- User ---------------
        """
        pass
        # terminal_width = self._get_max_output_width()
        # title_formatted = f"--- {title} " if title else ""
        # padding = "-" * (terminal_width - len(title_formatted)) if terminal_width > 0 else ""
        # self._output(f"\n{title_formatted}{padding}")
        # try:
        #     yield
        # finally:
        #     pass
    
    @contextmanager  
    def group(self, title: str, count: Optional[int] = None) -> Generator[None, None, None]:
        """
        Group/item header with optional count
        [ Requirements (3) ]
        """
        count_str = f" ({count})" if count is not None else ""
        self.show(f"[ {title}{count_str} ]")
        
        # Enter deeper indent level for group contents
        old_level = self.current_level
        self.current_level += 1
        try:
            yield
        finally:
            self.current_level = old_level

    def display_comment(self, message: str) -> None:
        self.show(f"❝ {message}")

    def display_error(self, message: str) -> None:
        self.show(f"✖ {message}")

    def display_warning(self, message: str) -> None:
        self.show(f"⚠ {message}")

    # def _format_question(self, question: str) -> str:
    #     """Utility method to format a question prompt."""
    #     question = question.strip()
    #     if not question.startswith("?"):
    #         question = f"? {question}"
    #
    #     return f"{question} "

    def ask_user(self, question: str = DEFAULT_INPUT_PROMPT, level: int | None = None) -> str:
        """Ask user a question and get a response."""
        indent = self._indent(level)
        return self._input(f"{indent}? {question}")

    def ask_yes_no(self, question: str, yes_values=None, auto_format: bool = True, level: int | None = None) -> bool:
        """Ask user a yes/no question."""
        if auto_format:
            if not "y/n" in question.lower():
                question = f"{question.strip()} [y/N]: "
        response = self.ask_user(question, level=level)
        if yes_values is None:
            yes_values = self.DEFAULT_YES
        return response.lower() in yes_values
    #
    # @abstractmethod
    # def display_status(self, message: str) -> None:
    #     """Display a status message."""
    #     pass
    
    # @abstractmethod
    # def display_verbose_info(self, message: str) -> None:
    #     """Display verbose/debug information (only if verbose mode enabled)."""
    #     pass