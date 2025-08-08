"""
Base interface classes for Solveig user interaction.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

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

    @abstractmethod
    def display_section_header(self, title: str) -> None:
        """Display a section header (e.g., '--- User ---')."""
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
    def display_requirements_header(self, count: int) -> None:
        """Display header for requirements section."""
        pass

    @abstractmethod
    def display_results_header(self, count: int) -> None:
        """Display header for requirement results section."""
        pass

    @abstractmethod
    def display_error(self, message: str) -> None:
        """Display an error message."""
        pass

    @abstractmethod
    def display_status(self, message: str) -> None:
        """Display a status message (e.g., '(Sending)')."""
        pass

    @abstractmethod
    def prompt_user(self, prompt: str | None = None) -> str:
        """Get text input from user."""
        pass

    @abstractmethod
    def ask_yes_no(self, prompt: str) -> bool:
        """Ask user a yes/no question."""
        pass

    @abstractmethod
    def display_verbose_info(self, message: str) -> None:
        """Display verbose/debug information (only if verbose mode enabled)."""
        pass
