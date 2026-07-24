"""
The display protocol for Solveig's frontends.

`SolveigInterface` is what a UI (CLI, web, desktop, headless mock) implements:
render (display_*), ask (ask_*), scope output (with_group), status and
animations, theming, and the reactive handshake (attach_conversation). It
deliberately also carries the two concerns every interactive frontend shares
- producer callbacks (on_user_input/on_edit_config_field, wired by run.py)
and cancellation (with_cancellable + the _active_operations registry + both
cancel verbs). App-session state (the input Inbox) and command dispatch live
OUTSIDE the interface - see solveig/inbox.py and decisions D0/D5.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from os import PathLike
from typing import TYPE_CHECKING, Any

from solveig.exceptions import UserCancel
from solveig.utils.file import FileMetadata

if TYPE_CHECKING:
    from solveig.conversation import Conversation
    from solveig.interface.themes import Palette
    from solveig.sessions.manager import SessionManager


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
    The display protocol any UI implementation (CLI, web, desktop, headless
    mock) provides: render, ask, scope, status/animation, theme, and the
    reactive handshake (`attach_conversation`).

    Two cross-cutting concerns are protocol-level ON PURPOSE (every UI with
    user input shares them, so a frontend never re-implements them):

    - **Producer callbacks** (`on_user_input`, `on_edit_config_field`) -
      wired by run.py at construction; the interface produces input without
      naming app objects (the Inbox, the SubcommandRunner). Decision D5.
    - **Cancellation** (`with_cancellable`, the `_active_operations`
      registry, `cancel_operation`/`cancel_active_operation`,
      `has_active_operations`) - every interactive UI has both a
      per-operation cancel (a button) and a global untargeted one (Esc,
      Ctrl+.), so the registry and both verbs live here.

    What is NOT here: the input queue (owned by run.py's main loop -
    `solveig/inbox.py`), prompt serialization policy (each frontend's own,
    e.g. the CLI's `_choice_lock`), and command dispatch (the runner's).
    """

    # App-wired producer callback: the ONE way user-typed input leaves the
    # interface (prompts and retries alike). Called as
    # `on_user_input(self, text)` - the interface passes itself, so the app's
    # router needs no closure over the interface (constructor-wirable, no
    # late-binding trick). Awaitable because the router awaits dispatch.
    on_user_input: Callable[[SolveigInterface, str], Awaitable[None]] | None = None
    # App-wired click-to-edit callback (stats bar cells), same shape:
    # `on_edit_config_field(self, field_name)`.
    on_edit_config_field: Callable[[SolveigInterface, str], Awaitable[None]] | None = (
        None
    )

    _root_ref: SolveigInterface | None = None
    _active_operations_ref: dict[asyncio.Task, None] | None = None

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
    def _active_operations(self) -> dict[asyncio.Task, None]:
        """Registration-ordered set of in-flight cancellable OPERATIONS,
        shared by every scope rooted at this interface (a group's
        `with_cancellable` registers on the root, so cancellation works no
        matter which scope declared the operation). A dict for O(1) targeted
        removal; insertion order gives "latest" for the global cancel."""
        root = self._root
        if root._active_operations_ref is None:
            root._active_operations_ref = {}
        return root._active_operations_ref

    @property
    def has_active_operations(self) -> bool:
        """Anything in flight the user could cancel?"""
        return any(not t.done() for t in self._active_operations)

    def cancel_operation(self, task: asyncio.Task) -> bool:
        """Targeted cancel (a per-operation button). The frontend holds the
        task handle from its own display of in-flight operations."""
        if not task.done():
            task.cancel()
            return True
        return False

    def cancel_active_operation(self) -> bool:
        """Global untargeted cancel (Esc/Ctrl+.): the LATEST unfinished
        operation - the only attribution an untargeted keystroke can have."""
        for task in reversed(list(self._active_operations)):
            if not task.done():
                task.cancel()
                return True
        return False

    @asynccontextmanager
    async def with_cancellable(
        self,
        coro: Any,
        status: str | None = None,
        final_status: str | None = None,
        timeout: float | None = None,
    ) -> AsyncGenerator[asyncio.Task]:
        """Declare `coro` a busy, user-cancellable OPERATION: run it as a task,
        register it in `_active_operations`, show `status` while it runs,
        unregister when done. Cancellation mechanics live HERE (cancel_operation
        / cancel_active_operation) - every UI with input has both a per-
        operation cancel (a button) and a global untargeted one (Esc, Ctrl+.),
        so the registry + both verbs are protocol, not per-frontend rewrites.
        """
        task = asyncio.ensure_future(coro)
        self._active_operations[task] = None
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
            self._active_operations.pop(task, None)

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

        Delegates to the root interface. Prompt SERIALIZATION (one visible
        prompt at a time) is the frontend's own policy, implemented inside
        its `_ask_*` - a terminal locks, a web UI may stack prompt cards."""
        return await self._root._ask_question(question, default)

    async def _ask_question(self, question: str, default: str = "") -> str:
        raise NotImplementedError("Subclass must implement _ask_question")

    async def ask_choice(
        self, question: str, choices: Iterable[str], add_cancel: bool = True
    ) -> int:
        """Ask a multiple-choice question, returns the index for the selected
        option (starting at 0). The prompt itself delegates to the root
        interface (serialization is the frontend's policy - see ask_question)
        - but the answer is echoed via `self.display_text`, so it lands in
        the caller's own scope (e.g. inside a tool's group) rather than
        always at the root."""
        choices_list = list(choices)
        if add_cancel:
            choices_list.append("Cancel processing")

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
