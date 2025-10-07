"""
Base interface protocol for Solveig.

Defines the minimal interface that any UI implementation (CLI, web, desktop) should provide.
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager, asynccontextmanager
from typing import Callable, Union, Awaitable, Optional, AsyncGenerator, Any


class SolveigInterface(ABC):
    """
    Abstract base class defining the core interface any Solveig UI must implement.

    This is intentionally minimal and focused on what Solveig actually needs:
    - Display text with basic styling
    - Get user input (both free-flow and prompt-based)
    - Standard error/warning/success messaging
    - Optional status display
    """

    def __init__(self, **kwargs):
        self.input_callback: Optional[Callable[["SolveigInterface", str], Union[None, Awaitable[None]]]] = None

    # Core display methods
    @abstractmethod
    def display_text(self, text: str, style: str = "normal") -> None:
        """Display text with optional styling."""
        ...

    @abstractmethod
    def display_error(self, error: str) -> None:
        """Display an error message with standard formatting."""
        ...

    @abstractmethod
    def display_warning(self, warning: str) -> None:
        """Display a warning message with standard formatting."""
        ...

    @abstractmethod
    def display_success(self, message: str) -> None:
        """Display a success message with standard formatting."""
        ...

    @abstractmethod
    def display_comment(self, message: str) -> None:
        """Display a comment message."""
        ...

    @abstractmethod
    def display_text_block(self, text: str, title: str = None) -> None:
        """Display a text block with optional title."""
        ...

    # Input methods
    @abstractmethod
    async def ask_user(self, prompt: str, placeholder: str = None) -> str:
        """Ask for specific input, preserving any current typing."""
        ...

    @abstractmethod
    async def ask_yes_no(self, question: str, yes_values=None, no_values=None) -> bool:
        """Ask a yes/no question."""
        ...

    def set_input_callback(self, callback: Optional[Callable[["SolveigInterface", str], Union[None, Awaitable[None]]]]):
        """Set callback for free-flow input (normal conversation)."""
        self.input_callback = callback

    # Optional methods
    @abstractmethod
    def set_status(self, status: str) -> None:
        """Update status display (if supported)."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Start the interface (if needed)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the interface (if needed)."""
        ...

    # Additional methods for compatibility
    @abstractmethod
    def display_section(self, title: str) -> None:
        """Display a section header."""
        ...

    @abstractmethod
    @contextmanager
    def with_group(self, title: str):
        """Context manager for grouping related output."""
        ...

    @abstractmethod
    @asynccontextmanager
    async def with_animation(self, status: str = "Processing", final_status: str = "Ready") -> AsyncGenerator[None, Any]:
        """Context manager for displaying animation during async operations."""
        ...