"""
Base interface classes for Solveig user interaction.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from solveig.interface import themes
from solveig.utils.file import Metadata

if TYPE_CHECKING:
    from solveig.schema.message import AssistantMessage


class SolveigInterface(ABC):
    """Abstract base class for all Solveig user interfaces."""

    DEFAULT_INPUT_PROMPT = ">  "
    DEFAULT_YES = {"y", "yes"}

    def __init__(
        self,
        indent_base: int = 2,
        max_lines=6,
        theme: themes.Palette = themes.DEFAULT,
        verbose: bool = False,
    ):
        self.indent_base = indent_base
        self.current_level = 0
        self.max_lines = max_lines
        self.verbose = verbose
        self.theme = theme

    @abstractmethod
    def _output(self, text: str, **kwargs) -> None:
        """Raw output method - implemented by concrete interfaces"""
        pass

    @abstractmethod
    def _input(self, prompt: str, **kwargs) -> str:
        """Get text input from user."""
        pass

    @abstractmethod
    def display_llm_response(self, llm_response: "AssistantMessage") -> None:
        """Display the assistant's comment and requirements summary."""
        pass

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
        metadata: Metadata,
        level: int | None = None,
        max_lines: int | None = None,
        title: str | None = None,
        display_metadata: bool = False,
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

    @abstractmethod
    def display_animation_while(
        self,
        run_this: Callable,
        message: str | None = None,
        animation_type: str | None = None,
    ) -> Any:
        pass

    #####

    def _indent(self, level: int | None = None) -> str:
        """Calculate indentation for given level (or current level)"""
        actual_level = level if level is not None else self.current_level
        return " " * (actual_level * self.indent_base)

    def display_text(
        self,
        text: str,
        level: int | None = None,
        truncate: bool = False,
        **kwargs,
    ) -> None:
        """Display content at specified or current indent level"""
        indent = self._indent(level)
        self._output(f"{indent}{text}", **kwargs)

    @contextmanager
    def with_indent(self) -> Generator[None]:
        """Indents the current level until released"""
        old_level = self.current_level
        self.current_level += 1
        try:
            yield
        finally:
            self.current_level = old_level

    @contextmanager
    def with_group(self, title: str) -> Generator[None]:
        """
        Group/item header with optional count
        [ Requirements (3) ]
        """
        self.display_text(f"[ {title} ]")

        # Use the with_indent context manager internally
        with self.with_indent():
            yield

    def display_comment(self, message: str) -> None:
        self.display_text(f"❝  {message}")

    def display_success(self, message: str) -> None:
        self.display_text(f"✓  {message}")

    def display_error(
        self, message: str | Exception | None = None, exception: Exception | None = None
    ) -> None:
        raise NotImplementedError()

    def display_warning(self, message: str) -> None:
        self.display_text(f"⚠  {message}")

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
