"""
Base interface classes for Solveig user interaction.
"""

from abc import ABC, abstractmethod
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from solveig.schema import LLMMessage


class SolveigInterface(ABC):
    """Abstract base class for all Solveig user interfaces."""

    DEFAULT_INPUT_PROMPT = ">  "
    DEFAULT_YES = {"y", "yes"}

    def __init__(self, indent_base: int = 2, max_lines=6, be_verbose: bool = False):
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

    # display_requirement removed - requirements now display themselves directly

    @abstractmethod
    def display_text_block(
        self,
        text: str,
        title: str | None = None,
        level: int | None = None,
        max_lines: int | None = None,
    ) -> None:
        """Display a block of text."""
        pass

    @abstractmethod
    def display_tree(
        self,
        metadata: dict[str, Any],
        listing: list[dict[str, Any]] | None,
        level: int | None = None,
        max_lines: int | None = None,
        title: str | None = "Metadata",
    ) -> None:
        """Utility method to display a block of text with metadata"""
        pass

    @abstractmethod
    def display_section(self, title: str) -> None:
        """
        Section header with line
        --- User ---------------
        """
        pass

    #####

    def _indent(self, level: int | None = None) -> str:
        """Calculate indentation for given level (or current level)"""
        actual_level = level if level is not None else self.current_level
        return " " * (actual_level * self.indent_base)

    def show(self, content: str, level: int | None = None) -> None:
        """Display content at specified or current indent level"""
        indent = self._indent(level)
        self._output(f"{indent}{content}")

    @contextmanager
    def with_indent(self) -> Generator[None, None, None]:
        """Indents the current level until released"""
        old_level = self.current_level
        self.current_level += 1
        try:
            yield
        finally:
            self.current_level = old_level

    @contextmanager
    def with_group(
        self, title: str, count: int | None = None
    ) -> Generator[None, None, None]:
        """
        Group/item header with optional count
        [ Requirements (3) ]
        """
        count_str = f" ({count})" if count is not None else ""
        self.show(f"[ {title}{count_str} ]")

        # Use the with_indent context manager internally
        with self.with_indent():
            yield

    def display_comment(self, message: str) -> None:
        self.show(f"❝  {message}")

    def display_error(self, message: str | Exception | None = None) -> None:
        self.show(f"✖  {message}")

    def display_warning(self, message: str) -> None:
        self.show(f"⚠  {message}")

    def ask_user(
        self, question: str = DEFAULT_INPUT_PROMPT, level: int | None = None
    ) -> str:
        """Ask user a question and get a response."""
        indent = self._indent(level)
        return self._input(f"{indent}?  {question}")

    def ask_yes_no(
        self,
        question: str,
        yes_values=None,
        auto_format: bool = True,
        level: int | None = None,
    ) -> bool:
        """Ask user a yes/no question."""
        if auto_format:
            question = f"{question.strip()} "
            if "y/n" not in question.lower():
                question = f"{question}[y/N]: "
        response = self.ask_user(question, level=level)
        if yes_values is None:
            yes_values = self.DEFAULT_YES
        return response.lower() in yes_values
