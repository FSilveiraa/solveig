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
from typing import TYPE_CHECKING, Any, Literal

from solveig.exceptions import UserCancel
from solveig.utils.file import FileMetadata

if TYPE_CHECKING:
    from solveig.conversation import Conversation
    from solveig.interface.themes import Palette
    from solveig.sessions.manager import SessionManager
    from solveig.subcommand.runner import SubcommandRunner


class MutableTextBox:
    def append(self, text: str) -> None:
        """Append text to the end of the box."""

    def clear(self) -> None:
        """Empty the box content."""


class EditableMessage:
    """What a message widget must implement to host action buttons
    (Edit/Retry/Delete/Branch)."""

    async def begin_edit(self) -> None:
        """Prompt for replacement text and overwrite this message in place."""

    async def retry(self) -> None:
        """Drop this message and everything after it, then resubmit its
        text as a fresh prompt."""

    async def delete_from_here(self) -> None:
        """Drop this message and everything after it."""

    async def branch_from_here(self) -> None:
        """Store the current conversation as a checkpoint, then drop this
        message and everything after it."""


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
    _request_task_stack_ref: list[asyncio.Task] | None = None
    _root_ref: SolveigInterface | None = None
    _choice_lock_ref: asyncio.Lock | None = None

    def set_theme(self, theme: Palette) -> None:
        """Re-theme the live interface (the colours used for both CSS and Rich
        markup). Concrete UIs override this; a headless interface leaves it as
        the no-op default."""
        return None

    @property
    def _root(self) -> SolveigInterface:
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

    @property
    def _request_tasks(self) -> list[asyncio.Task]:
        """Stack of in-flight cancellable tasks, lazily created and shared
        across every scope rooted at this interface (accessed only via
        self._root._request_tasks) - unrelated to group nesting; a tool's own
        with_cancellable (e.g. CommandTool's shell run) pushes onto the same
        stack as the outer per-tool-call one even though it runs against a
        scoped GroupInterface, not the root, so cancel_request() (always
        called on the root) can still see and target it. The top of the
        stack is always the innermost currently-active cancellable, so
        Ctrl+C/Esc cancels exactly that one - e.g. hitting cancel while a
        command is running triggers CommandTool's own cancellation handling
        instead of the generic outer one."""
        if self._request_task_stack_ref is None:
            self._request_task_stack_ref = []
        return self._request_task_stack_ref

    def set_subcommand_executor(self, subcommand_executor: SubcommandRunner):
        self.subcommand_executor = subcommand_executor

    async def notify_pending_queue_changed(self) -> None:
        """Called after an item is put onto or taken off `pending_queue`.

        Default no-op; concrete interfaces that display a live queued-message
        indicator (e.g. `TerminalInterface`) override this to refresh it.
        Prefer `enqueue_pending`/`dequeue_pending`/`try_dequeue_pending`
        below over touching `pending_queue` directly - they call this for
        you, so there's no "remember to notify after every mutation" to get
        wrong at a new call site.
        """
        root = self._root
        if root is not self:
            await root.notify_pending_queue_changed()

    async def enqueue_pending(self, text: str) -> None:
        """Put `text` onto the ROOT's `pending_queue` and refresh the display.

        Root-global like `ask_choice`/`start`: scoped interfaces (groups)
        don't own a queue - the one consumer is the root's main loop.
        """
        await self._root.pending_queue.put(text)
        await self.notify_pending_queue_changed()

    async def dequeue_pending(self) -> str:
        """Wait for and remove the next queued prompt, refreshing the display."""
        text = await self._root.pending_queue.get()
        await self.notify_pending_queue_changed()
        return text

    async def try_dequeue_pending(self) -> str | None:
        """Remove the next queued prompt without waiting, or `None` if empty -
        refreshing the display only when something was actually taken."""
        if self._root.pending_queue.empty():
            return None
        text = self._root.pending_queue.get_nowait()
        await self.notify_pending_queue_changed()
        return text

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
        stack = self._root._request_tasks
        stack.append(task)
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
            stack.remove(task)

    def cancel_request(self) -> bool:
        """Cancel the innermost active cancellable task (top of the stack).

        Returns True if there was an active request to cancel,
        False otherwise.
        """
        stack = self._root._request_tasks
        if stack and not stack[-1].done():
            stack[-1].cancel()
            return True
        return False

    @property
    def has_active_request(self) -> bool:
        """Check if there's an active cancellable task running."""
        stack = self._root._request_tasks
        return bool(stack) and not stack[-1].done()

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

    async def attach_conversation(
        self, conversation: Conversation, session_manager: SessionManager
    ) -> None:
        """Subscribe this interface's reactive transcript to `conversation`
        once both exist. Interface-agnostic: the Textual interface mounts a
        `TextualTranscript`; a future web frontend would mount its own observer;
        a headless mock may no-op. Called once, after the interface is ready."""
        return None

    @abstractmethod
    async def display_comment(
        self,
        role: Literal["user", "assistant"],
        message: str,
        *,
        conversation: Conversation,
        session_manager: SessionManager,
        message_id: str,
        part_index: int,
    ) -> None:
        """Display a user/assistant text message wired to the conversation
        entry `message_id` (part `part_index`), with Edit/Retry/Delete/Branch
        action buttons. Used by session replay; live turns render reactively
        through the transcript instead."""
        ...

    @abstractmethod
    async def clear_conversation(self) -> None:
        """Remove all currently displayed conversation content, in
        preparation for a full redraw after a delete/retry/branch."""
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
    async def ask_question(self, question: str, default: str = "") -> str:
        """Ask for specific input, preserving any current typing.

        Delegates to the root interface and serializes against any other
        concurrently-pending ask_question/ask_choice call - a terminal (or
        any single-user UI) can only show one prompt at a time, regardless
        of how many groups are concurrently asking."""
        async with self._root._choice_lock:
            return await self._root._ask_question(question, default)

    async def _ask_question(self, question: str, default: str = "") -> str:
        raise NotImplementedError("Subclass must implement _ask_question")

    async def ask_choice(
        self, question: str, choices: Iterable[str], add_cancel: bool = True
    ) -> int:
        """Ask a multiple-choice question, returns the index for the selected
        option (starting at 0). The prompt itself delegates to the root
        interface and serializes against other concurrent prompts - see
        ask_question - but the answer is echoed via `self.display_text`, so
        it lands in the caller's own scope (e.g. inside a tool's group)
        rather than always at the root."""
        choices_list = list(choices)
        if add_cancel:
            choices_list.append("Cancel processing")

        async with self._root._choice_lock:
            choice_index = await self._root._ask_choice(question, choices_list)
        await self.display_text(choices_list[choice_index], prefix=question)
        if add_cancel and choice_index == len(choices_list) - 1:
            raise UserCancel()
        return choice_index

    async def _ask_choice(self, question: str, choices: list[str]) -> int:
        raise NotImplementedError("Subclass must implement _ask_choice")

    # Additional methods for compatibility
    async def display_section(self, title: str, even_if_repeated: bool = False) -> None:
        """Display a section header. Delegates to the root interface."""
        await self._root._display_section(title, even_if_repeated)

    async def _display_section(
        self, title: str, even_if_repeated: bool = False
    ) -> None:
        raise NotImplementedError("Subclass must implement _display_section")

    @asynccontextmanager
    async def with_group(
        self, title: str, auto_collapse: bool = False
    ) -> AsyncGenerator[SolveigInterface, Any]:
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
        async with self._root._with_animation(
            status, final_status, timeout, suffix
        ) as value:
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
