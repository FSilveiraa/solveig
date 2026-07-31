"""
The display protocol for Solveig's frontends.

`SolveigInterface` is what a UI (CLI, web, desktop, headless mock) implements:
render (display_*), ask (ask_*), scope output (with_group), status and
animations, theming, and the reactive handshake (attach_conversation). It
deliberately also carries the two concerns every interactive frontend shares
- the user-message queue (the interface's output channel for typed input)
and cancellation (with_cancellable + the _active_tasks registry + the
cancel_task verb). Command dispatch lives OUTSIDE the interface - the queue's
prompt gate routes /commands before insertion.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from os import PathLike
from typing import TYPE_CHECKING, Any

from solveig.exceptions import UserCancel
from solveig.utils.file import FileMetadata

if TYPE_CHECKING:
    from solveig.conversation import Conversation
    from solveig.interface.themes import Palette
    from solveig.user_message_queue import UserMessageQueue


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

    - **User-message queue** (`user_message_queue`) - the interface's output
      channel for typed input. The interface `put`s; the queue's prompt gate
      decides what actually lands (prompts vs swallowed /commands).
    - **Cancellation** (`with_cancellable`, the `_active_tasks`
      registry, `cancel_task`, `get_active_tasks`) - every interactive UI has
      both a per-task cancel (a button) and a global untargeted one (Esc,
      Ctrl+.), so the registry and the verb live here.

    What is NOT here: prompt serialization policy (each frontend's own,
    e.g. the CLI's `_choice_lock`) and command dispatch (the queue gate's).
    """

    # The interface's output channel: typed input goes here. Set by
    # constructor (real frontends) or post-construction by the composition
    # root (injected test/demo interfaces). None until wired; `_handle_input`
    # no-ops without it.
    user_message_queue: UserMessageQueue | None = None

    _root_ref: SolveigInterface | None = None
    _active_tasks_ref: dict[asyncio.Task, None] | None = None

    def set_theme(self, theme: Palette) -> None:
        """Re-theme the live interface (the colours used for both CSS and Rich
        markup). Concrete UIs override this; a headless interface leaves it as
        the no-op default."""
        return None

    def set_code_theme(self, code_theme: str) -> None:
        """Update the pygments theme used for Syntax/code blocks. New renders
        pick it up; concrete UIs may also refresh already-mounted code views
        in place. Must not remount the conversation tree. Default is a no-op."""
        return None

    @property
    def _root(self) -> SolveigInterface:
        """The top-level interface backing this scope - itself, unless this
        is a scoped child (e.g. a GroupInterface) returned by with_group()."""
        return self._root_ref if self._root_ref is not None else self

    @property
    def _active_tasks(self) -> dict[asyncio.Task, None]:
        """Registration-ordered set of in-flight cancellable TASKS, shared by
        every scope rooted at this interface (a group's `with_cancellable`
        registers on the root, so cancellation works no matter which scope
        declared the task). A dict for O(1) targeted removal; insertion order
        gives "latest" for the untargeted cancel."""
        root = self._root
        if root._active_tasks_ref is None:
            root._active_tasks_ref = {}
        return root._active_tasks_ref

    def get_active_tasks(self) -> dict[asyncio.Task, None]:
        """The in-flight cancellable tasks, registration-ordered. Empty is
        falsy, so `if interface.get_active_tasks():` is the busy check."""
        return self._active_tasks

    def cancel_task(self, task: asyncio.Task | None = None) -> bool:
        """Cancel one in-flight task: the GIVEN one (a per-task button), or
        the LATEST registered when None (Esc/Ctrl+. - an untargeted keystroke
        can only mean "the most recent thing"). Same verb at both targeting
        resolutions, like list.pop() with and without an index."""
        candidates = [task] if task is not None else reversed(list(self._active_tasks))
        for t in candidates:
            if t is not None and not t.done():
                t.cancel()
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
        """Declare `coro` a busy, user-cancellable piece of work: run it as a
        task, register it in `_active_tasks`, show `status` while it runs,
        unregister when done. Cancellation mechanics live HERE (cancel_task,
        targeted or latest) - every UI with input has both a per-task cancel
        (a button) and a global untargeted one (Esc, Ctrl+.), so the registry
        and the verb are protocol, not per-frontend rewrites.
        """
        task = asyncio.ensure_future(coro)
        self._active_tasks[task] = None
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
            self._active_tasks.pop(task, None)

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

    async def attach_conversation(self, conversation: Conversation) -> None:
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

        A user-addressable wait is a registered task like any other: while
        the prompt is open it sits in `_active_tasks`, so a targeted cancel
        (a per-prompt ✕) or an untargeted one (Esc -> cancel_task()) reaches
        it through the SAME machinery as background work - but prompts are
        NOT wrapped in `with_cancellable` (they're waits, not work; no
        spinner, and no "callers must remember to wrap" burden - the
        registration lives here, at the one seam). A cancel at the prompt
        boundary is translated CancelledError -> UserCancel: to the caller,
        Esc during a question is the user ANSWERING "cancel", identical to
        picking a Cancel menu item. Prompt CONCURRENCY is each frontend's
        policy (inside its `_ask_*`): a terminal may lock, Textual can show
        stacked prompts, a web UI stacks cards.
        """
        task = asyncio.ensure_future(self._root._ask_question(question, default))
        self._active_tasks[task] = None
        try:
            return await task
        except asyncio.CancelledError:
            raise UserCancel from None
        finally:
            self._active_tasks.pop(task, None)

    async def _ask_question(self, question: str, default: str = "") -> str:
        raise NotImplementedError("Subclass must implement _ask_question")

    async def ask_choice(
        self, question: str, choices: Iterable[str], add_cancel: bool = True
    ) -> int:
        """Ask a multiple-choice question, returns the index for the selected
        option (starting at 0). The prompt-wait is a cancellable like any
        other (see ask_question for the full why): Esc during a choice is
        translated to UserCancel at the boundary, i.e. the same control flow
        as picking the appended "Cancel processing" item - call sites handle
        both identically. The answer is echoed via `self.display_text`, so
        it lands in the caller's own scope (e.g. inside a tool's group)
        rather than always at the root."""
        choices_list = list(choices)
        if add_cancel:
            choices_list.append("Cancel processing")

        task = asyncio.ensure_future(self._root._ask_choice(question, choices_list))
        self._active_tasks[task] = None
        try:
            choice_index = await task
        except asyncio.CancelledError:
            raise UserCancel from None
        finally:
            self._active_tasks.pop(task, None)
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
