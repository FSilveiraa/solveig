"""
Base interface protocol for Solveig.

Defines the minimal interface that any UI implementation (CLI, web, desktop) should provide.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from contextlib import asynccontextmanager
from os import PathLike

from solveig.subcommand import SubcommandRunner
from solveig.utils.file import Metadata


class SolveigInterface(ABC):
    """
    Abstract base class defining the core interface any Solveig UI must implement.

    This is intentionally minimal and focused on what Solveig actually needs:
    - Display text with basic styling
    - Get user input (both free-flow and prompt-based)
    - Standard error/warning/success messaging
    - Optional status display
    """

    subcommand_executor: SubcommandRunner | None = None

    def set_subcommand_executor(self, subcommand_executor: SubcommandRunner):
        self.subcommand_executor = subcommand_executor

    @abstractmethod
    async def start(self) -> None:
        """Start the interface."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the interface explicitly."""
        ...

    @abstractmethod
    async def wait_until_ready(self):
        """Wait until the interface is ready to be used."""
        ...

    # Core display methods
    @abstractmethod
    async def display_text(self, text: str, style: str = "normal") -> None:
        """Display text with optional styling."""
        ...

    @abstractmethod
    async def display_error(self, error: str | Exception) -> None:
        """Display an error message with standard formatting."""
        ...

    @abstractmethod
    async def display_warning(self, warning: str) -> None:
        """Display a warning message with standard formatting."""
        ...

    @abstractmethod
    async def display_success(self, message: str) -> None:
        """Display a success message with standard formatting."""
        ...

    @abstractmethod
    async def display_comment(self, message: str) -> None:
        """Display a comment message."""
        ...

    @abstractmethod
    async def display_tree(
        self,
        metadata: Metadata,
        title: str | None = None,
        display_metadata: bool = False,
    ) -> None:
        """Display a tree structure of a directory"""
        ...

    @abstractmethod
    async def display_text_block(
        self, text: str, title: str | None = None, language: str | None = None
    ) -> None:
        """Display a text block with optional title."""
        ...

    @abstractmethod
    async def display_diff(
        self,
        old_content: str,
        new_content: str,
        title: str | None = None,
        context_lines: int = 3,
    ) -> None:
        """Display a unified diff view with syntax highlighting."""
        ...

    # Input methods
    @abstractmethod
    async def get_input(self) -> str:
        """Get user input for conversation flow."""
        ...

    @abstractmethod
    async def ask_user(self, prompt: str, placeholder: str | None = None) -> str:
        """Ask for specific input, preserving any current typing."""
        ...

    @abstractmethod
    async def ask_yes_no(
        self, question: str, yes_values: Iterable[str] | None = None
    ) -> bool:
        """Ask a yes/no question."""
        ...

    # Additional methods for compatibility
    @abstractmethod
    async def display_section(self, title: str) -> None:
        """Display a section header."""
        ...

    @asynccontextmanager
    async def with_group(self, title: str):
        """Context manager for grouping related output."""
        raise NotImplementedError("Subclass must implement with_group")
        yield  # This line will never execute but makes it a valid generator

    @asynccontextmanager
    async def with_animation(
        self, status: str = "Processing", final_status: str = "Ready"
    ):
        """Context manager for displaying animation during async operations."""
        raise NotImplementedError("Subclass must implement with_animation")
        yield  # This line will never execute but makes it a valid generator

    @abstractmethod
    async def update_status(
        self,
        status: str | None = None,
        tokens: tuple[int, int] | int | str | None = None,
        model: str | None = None,
        url: str | None = None,
    ) -> None:
        """Update status bar with multiple pieces of information."""
        ...

    @abstractmethod
    async def display_file_info(
        self,
        source_path: str | PathLike,
        destination_path: str | PathLike | None = None,
        is_directory: bool | None = None,
        source_content: str | None = None,
        show_overwrite_warning: bool = True,
    ) -> None:
        """Display move requirement header."""
