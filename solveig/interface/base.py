"""
Base interface protocol for Solveig.

Defines the minimal interface that any UI implementation (CLI, web, desktop) should provide.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from os import PathLike
from typing import TYPE_CHECKING, Any

from solveig.utils.file import FileMetadata

if TYPE_CHECKING:
    from solveig.subcommand.runner import SubcommandRunner


class MutableTextBox:
    def append(self, text: str) -> None:
        """Append text to the end of the box."""

    def reset(self, text: str) -> None:
        """Reset the box content."""


class SolveigInterface(ABC):
    """
    Abstract base class defining the core interface any UI implementation (CLI, web, desktop) should provide.

    This is intentionally minimal and focused on what Solveig actually needs:
    - Display text with basic styling
    - Get user input (both free-flow and prompt-based)
    - Standard error/warning/success messaging
    - Optional status display
    """

    subcommand_executor: SubcommandRunner | None = None
    pending_queue: asyncio.Queue
    _request_task: asyncio.Task | None = None
    _root_ref: "SolveigInterface | None" = None
    _choice_lock_ref: asyncio.Lock | None = None

    @property
    def _root(self) -> "SolveigInterface":
        """The top-level interface backing this scope - itself, unless this
        is a scoped child (e.g. a GroupInterface) returned by with_group()."""
        return self._root_ref if self._root_ref is not None else self

    @property
    def _choice_lock(self) -> asyncio.Lock:
        """Lazily-created, shared across every scope rooted at this
        interface (accessed only via self._root._choice_lock)."""
        if self._choice_lock_ref is None:
            self._choice_lock_ref = asyncio.Lock()
        return self._choice_lock_ref

    def set_subcommand_executor(self, subcommand_executor: SubcommandRunner):
        self.subcommand_executor = subcommand_executor

    async def notify_pending_queue_changed(self) -> None:  # noqa: B027
        """Called after an item is put onto or taken off `pending_queue`.

        Default no-op; concrete interfaces that display a live queued-message
        indicator (e.g. `TerminalInterface`) override this to refresh it.
        """

    @asynccontextmanager
    async def with_cancellable(
        self,
        coro: Any,
        status: str | None = None,
        final_status: str | None = None,
        timeout: float | None = None,
    ) -> AsyncGenerator[asyncio.Task]:
        """Run a coroutine as a cancellable task. Ctrl+C / Esc will cancel it.

        Pass status to also show a spinner animation while the task runs.
        Pass timeout to display elapsed/max seconds in the animation.
        """
        task = asyncio.ensure_future(coro)
        self._request_task = task
        try:
            if status is not None:
                async with self.with_animation(
                    status,
                    final_status,
                    timeout=timeout,
                    suffix="(Esc/Ctrl+C to cancel)",
                ):
                    yield task
            else:
                yield task
        finally:
            self._request_task = None

    def cancel_request(self) -> bool:
        """Cancel the current network request task.

        Returns True if there was an active request to cancel,
        False otherwise.
        """
        if self._request_task is not None and not self._request_task.done():
            self._request_task.cancel()
            return True
        return False

    @property
    def has_active_request(self) -> bool:
        """Check if there's an active network request running."""
        return self._request_task is not None and not self._request_task.done()

    async def start(self) -> None:
        """Start the interface. Delegates to the root - only the root
        interface is ever actually started."""
        await self._root._start()

    async def _start(self) -> None:
        raise NotImplementedError("Subclass must implement _start")

    async def stop(self) -> None:
        """Stop the interface explicitly. Delegates to the root."""
        await self._root._stop()

    async def _stop(self) -> None:
        raise NotImplementedError("Subclass must implement _stop")

    async def wait_until_ready(self):
        """Wait until the interface is ready to be used. Delegates to the root."""
        return await self._root._wait_until_ready()

    async def _wait_until_ready(self):
        raise NotImplementedError("Subclass must implement _wait_until_ready")

    # Core display methods
    @abstractmethod
    async def display_text(self, text: str, prefix: str | None = None) -> None:
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
    async def display_info(self, message: str) -> None:
        """Display a system message."""
        ...

    @abstractmethod
    async def display_comment(self, message: str) -> None:
        """Display a comment message."""
        ...

    @abstractmethod
    async def display_tree(
        self,
        metadata: FileMetadata,
        title: str | None = None,
        display_metadata: bool = False,
        expand_root=True,
    ) -> None:
        """Display a tree structure of a directory"""
        ...

    @abstractmethod
    async def display_text_box(
        self,
        text: str,
        title: str | None = None,
        language: str | None = None,
        italic: bool = False,
        collapsed: bool = False,
    ) -> MutableTextBox:
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
    async def ask_question(self, question: str) -> str:
        """Ask for specific input, preserving any current typing.

        Delegates to the root interface and serializes against any other
        concurrently-pending ask_question/ask_choice call - a terminal (or
        any single-user UI) can only show one prompt at a time, regardless
        of how many groups are concurrently asking."""
        async with self._root._choice_lock:
            return await self._root._ask_question(question)

    async def _ask_question(self, question: str) -> str:
        raise NotImplementedError("Subclass must implement _ask_question")

    async def ask_choice(
        self, question: str, choices: Iterable[str], add_cancel: bool = True
    ) -> int:
        """Ask a multiple-choice question, returns the index for the selected
        option (starting at 0). Delegates to the root interface and
        serializes against other concurrent prompts - see ask_question."""
        async with self._root._choice_lock:
            return await self._root._ask_choice(question, choices, add_cancel)

    async def _ask_choice(
        self, question: str, choices: Iterable[str], add_cancel: bool = True
    ) -> int:
        raise NotImplementedError("Subclass must implement _ask_choice")

    # Additional methods for compatibility
    async def display_section(self, title: str, even_if_repeated: bool = False) -> None:
        """Display a section header. Delegates to the root interface."""
        await self._root._display_section(title, even_if_repeated)

    async def _display_section(self, title: str, even_if_repeated: bool = False) -> None:
        raise NotImplementedError("Subclass must implement _display_section")

    @asynccontextmanager
    async def with_group(
        self, title: str, auto_collapse: bool = False
    ) -> AsyncGenerator["SolveigInterface", Any]:
        """Context manager for grouping related output. Yields a
        SolveigInterface scoped to this group - local display calls made on
        it land inside the group; global calls (ask_choice, update_stats,
        etc.) transparently affect the root."""
        raise NotImplementedError("Subclass must implement with_group")
        yield  # This line will never execute but makes it a valid generator

    @asynccontextmanager
    async def with_animation(
        self,
        status: str = "Processing",
        final_status: str | None = None,
        timeout: float | None = None,
        suffix: str | None = None,
    ) -> AsyncGenerator[None]:
        """Context manager for displaying animation during async operations.
        Delegates to the root interface - there is only one status bar."""
        async with self._root._with_animation(status, final_status, timeout, suffix) as value:
            yield value

    @asynccontextmanager
    async def _with_animation(
        self,
        status: str = "Processing",
        final_status: str | None = None,
        timeout: float | None = None,
        suffix: str | None = None,
    ) -> AsyncGenerator[None]:
        raise NotImplementedError("Subclass must implement _with_animation")
        yield  # pragma: no cover - unreachable, makes this a valid generator

    async def update_stats(
        self,
        status: str | None = None,
        sent_tokens: int | None = None,
        received_tokens: int | None = None,
        model: str | None = None,
        url: str | None = None,
        path: str | PathLike | None = None,
        max_context: int | None = None,
        used_context: int | None = None,
        input_price: float | None = None,
        output_price: float | None = None,
        mcp_servers: list[str] | None = None,
        duration: float | None = None,
    ) -> None:
        """Update status bar with multiple pieces of information. Delegates
        to the root interface - there is only one status bar.

        Pass `duration` to show `status` as a flash message: it reverts to whatever
        status was set before this call once `duration` seconds pass, unless something
        else has changed the status in the meantime.
        """
        await self._root._update_stats(
            status=status,
            sent_tokens=sent_tokens,
            received_tokens=received_tokens,
            model=model,
            url=url,
            path=path,
            max_context=max_context,
            used_context=used_context,
            input_price=input_price,
            output_price=output_price,
            mcp_servers=mcp_servers,
            duration=duration,
        )

    async def _update_stats(
        self,
        status: str | None = None,
        sent_tokens: int | None = None,
        received_tokens: int | None = None,
        model: str | None = None,
        url: str | None = None,
        path: str | PathLike | None = None,
        max_context: int | None = None,
        used_context: int | None = None,
        input_price: float | None = None,
        output_price: float | None = None,
        mcp_servers: list[str] | None = None,
        duration: float | None = None,
    ) -> None:
        raise NotImplementedError("Subclass must implement _update_stats")
