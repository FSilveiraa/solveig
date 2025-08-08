"""
Base interface classes for Solveig user interaction.
"""
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generator, Optional

if TYPE_CHECKING:
    from ..schema.message import LLMMessage


@dataclass
class RequirementPresentation:
    """Data structure containing everything needed to display a requirement."""
    title: str
    comment: str
    details: list[str]
    warnings: list[str] | None = None
    content_preview: str | None = None


class SolveigInterface(ABC):
    """Abstract base class for all Solveig user interfaces."""
    
    def __init__(self, config, indent_base: int = 2):
        self.config = config
        self.indent_base = indent_base
        self.current_level = 0
    
    @abstractmethod
    def _output(self, text: str) -> None:
        """Raw output method - implemented by concrete interfaces"""
        pass
    
    @abstractmethod
    def _get_terminal_width(self) -> int:
        """Get terminal width - implemented by concrete interfaces"""
        pass
    
    def _indent(self, level: Optional[int] = None) -> str:
        """Calculate indentation for given level (or current level)"""
        actual_level = level if level is not None else self.current_level
        return " " * (actual_level * self.indent_base)
    
    def show(self, content: str, level: Optional[int] = None) -> None:
        """Display content at specified or current indent level"""
        indent = self._indent(level)
        self._output(f"{indent}{content}")
    
    @contextmanager
    def section(self, title: str) -> Generator[None, None, None]:
        """Section header with line (--- User ---)"""
        terminal_width = self._get_terminal_width()
        title_formatted = f"--- {title} " if title else ""
        line = "-" * (terminal_width - len(title_formatted))
        self._output(f"\n{title_formatted}{line}")
        try:
            yield
        finally:
            pass
    
    @contextmanager  
    def group(self, title: str, count: Optional[int] = None) -> Generator[None, None, None]:
        """Group/item header with optional count ([ Requirements (3) ])"""
        count_str = f" ({count})" if count is not None else ""
        self.show(f"[ {title}{count_str} ]")
        
        # Enter deeper indent level for group contents
        old_level = self.current_level
        self.current_level += 1
        try:
            yield
        finally:
            self.current_level = old_level
    
    @abstractmethod
    def prompt_user(self, prompt: str) -> str:
        """Get text input from user."""
        pass

    def ask_yes_no(self, prompt: str) -> bool:
        """Ask user a yes/no question."""
        response = self.prompt_user()
    
    @abstractmethod
    def display_llm_response(self, llm_response: "LLMMessage") -> None:
        """Display the LLM's comment and requirements summary."""
        pass
    
    @abstractmethod
    def display_requirement(self, presentation: RequirementPresentation) -> None:
        """Display a single requirement with its presentation data."""
        pass
    
    @abstractmethod
    def display_error(self, message: str) -> None:
        """Display an error message."""
        pass
    
    @abstractmethod
    def display_status(self, message: str) -> None:
        """Display a status message."""
        pass
    
    @abstractmethod
    def display_verbose_info(self, message: str) -> None:
        """Display verbose/debug information (only if verbose mode enabled)."""
        pass