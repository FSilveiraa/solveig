"""The display protocol for Solveig's frontends.

`SolveigInterface` is what a UI (CLI, web, desktop, headless mock) implements:
render (`print`, `display_*`, `add_*`), ask (`ask_*`), scope output
(`with_group`), status and animations, and theming. It also carries two
concerns every interactive frontend shares — the user-message queue (the
interface's output channel for typed input) and cancellation
(`with_cancellable` + the `_active_tasks` registry + `cancel_task`). Command
dispatch lives OUTSIDE the interface — the queue's prompt gate routes
/commands before insertion.

Naming conventions:
- `print`   — text output, void
- `add_`    — returns an object (add_text_box → MutableTextBox, add_stat → Stat)
- `with_`   — async context manager (with_group, with_animation, with_cancellable)
- `display_`— complex void rendering (display_tree, display_diff)
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from solveig.exceptions import UserCancel
from solveig.utils.file import FileMetadata

if TYPE_CHECKING:
    from solveig.interface.themes import Palette
    from solveig.session.conversation import Conversation, MessageId
    from solveig.user_message_queue import UserMessageQueue


class Level(Enum):
    TEXT = auto()
    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    SUCCESS = auto()


class Stat:
    """One entry in the stats display, handed out by `add_stat`.

    An INTERFACE concept, deliberately. There is no such thing as a stat nobody
    renders - unlike a `Conversation`, which earns a domain existence from
    persistence, replay and the messages it feeds the model, every consumer of a
    stat is a display. And placement is frontend-specific knowledge: the Textual
    bar puts the model in a known cell, a web UI might use a side list, so the
    frontend subclasses this to carry whatever it needs to lay one out. A
    registry outside the interface would have forced the frontend to identify
    stats by label or by registration order - a parallel structure to keep in
    step.

    Holds NO value. `get` reads the live source, so `config.api.model` stays the
    single home and there is nothing to drift or re-sync. A stat that cached its
    value would need an observer to keep the copy honest, which is one more
    thing than the observer that already exists.

    `on_click` takes nothing: whatever it needs (a config, an interface to
    prompt on) its owner closed over when registering. That is what keeps the
    behaviour of a config stat inside the config module - the widget calls a
    callable and never learns what a config is.
    """

    def __init__(
        self,
        label: str,
        get: Callable[[], Any],
        on_click: Callable[[], Awaitable[None]] | None = None,
        render: Callable[[Any], str] | None = None,
    ) -> None:
        self.label = label
        self.get = get
        self.on_click = on_click
        #: Value -> text. The OWNER knows a context stat reads "12/128k" or
        #: "Unlimited"; the frontend only knows where to put the result.
        self.render = render

    @property
    def text(self) -> str:
        value = self.get()
        return self.render(value) if self.render else str(value)

    @property
    def clickable(self) -> bool:
        return self.on_click is not None

    def refresh(self) -> None:
        """Redraw just this entry.

        The owner holds the stat, so it can say precisely what went stale
        instead of asking the whole display to re-read - which is the point of
        `add_stat` handing the object back. A frontend can honour this because
        it created the stat and knows where it put it.

        No-op by default: a headless interface has nothing to redraw, and a
        frontend that cannot address one entry may leave it and rely on
        `refresh_stats()`."""
        return None

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.label!r})"


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
    """The display protocol any UI implementation (CLI, web, desktop, headless
    mock) provides: render, ask, scope, status/animation, theme, and the
    conversation it displays (handed in at construction).

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

    def __init__(self) -> None:
        self._active_tasks: dict[asyncio.Task, None] = {}
        self.user_message_queue: UserMessageQueue | None = None
        self._conversation: Conversation | None = None

    @property
    def conversation(self) -> Conversation | None:
        return self._conversation

    # -- theming (no-op defaults, override per frontend) ---------------------

    def set_theme(self, theme: Palette) -> None:
        """Re-theme the live interface. No-op default; concrete UIs override."""
        return None

    def set_code_theme(self, code_theme: str) -> None:
        """Update the pygments theme. No-op default; concrete UIs override."""
        return None

    # -- cancellation (protocol-level, concrete) -----------------------------

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

    # -- text ----------------------------------------------------------------

    @abstractmethod
    async def print(
        self,
        text: str,
        level: Level = Level.TEXT,
        *,
        prefix: str | None = None,
    ) -> None:
        """Print text with a severity level and optional prefix.

        Ephemeral — never persisted in the conversation. Tool failures are
        captured in `ToolResult.issues` and returned via `to_tool_return()`;
        this call is a side-channel notification for the user's eyes only.
        """
        ...

    # -- transcript verbs ----------------------------------------------------
    # The three verbs the conversation observer drives. It decides WHAT should
    # be visible; a frontend only materializes what it is handed, and never
    # subscribes to the conversation itself.

    @abstractmethod
    async def show_message_part(self, message_id: MessageId, part_index: int) -> None:
        """Materialize one part of `self.conversation`'s message. Called in part
        order; a part this frontend has no rendering for is a no-op (the caller
        does not know, or need to know, which those are).

        Finer-grained than the other two because it is the only one with
        anything to interleave: the observer may draw a part itself in the
        middle of a message, so it has to hand parts over one at a time to keep
        them in order."""
        ...

    @abstractmethod
    async def update_message(self, message_id: MessageId) -> None:
        """Redraw an already-shown message in place - a streamed token landed,
        a stream finished, or the user edited it. Parts that appeared since the
        last call are appended."""
        ...

    @abstractmethod
    async def drop_messages(self, message_ids: list[MessageId]) -> None:
        """Remove these messages from the display. The ids may already be gone
        from the conversation, so this must work from the frontend's own
        record of what it mounted."""
        ...

    # -- complex display -----------------------------------------------------

    @abstractmethod
    async def display_tree(
        self,
        metadata: FileMetadata,
        title: str | None = None,
        display_metadata: bool = False,
        expand_root: bool = True,
    ) -> None:
        """Display a tree structure of a directory."""
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

    # -- add (returns object) ------------------------------------------------

    @abstractmethod
    async def add_text_box(
        self,
        text: str,
        title: str | None = None,
        language: str | None = None,
        italic: bool = False,
        collapsed: bool = False,
    ) -> MutableTextBox:
        """Add a text block with optional title. Returns a live box the
        caller can append to."""
        ...

    @abstractmethod
    def add_stat(
        self,
        label: str,
        get: Callable[[], Any],
        on_click: Callable[[], Awaitable[None]] | None = None,
        render: Callable[[Any], str] | None = None,
    ) -> Stat:
        """Declare a stat and hand it back. The interface CREATES it, so a
        frontend can return its own subclass carrying whatever it needs to
        place one. The caller keeps the returned object as its handle -
        identity is the object, never a name."""
        ...

    # -- with (context managers) ---------------------------------------------

    @asynccontextmanager
    @abstractmethod
    async def with_group(
        self, title: str, auto_collapse: bool = False
    ) -> AsyncGenerator[SolveigInterface, Any]:
        """Context manager for grouping related output. Yields a
        SolveigInterface scoped to this group — local calls land inside the
        group; global calls transparently affect the root."""
        yield self  # pragma: no cover - makes this a valid generator

    @asynccontextmanager
    @abstractmethod
    async def with_animation(
        self,
        status: str = "Processing",
        final_status: str | None = None,
        timeout: float | None = None,
        suffix: str | None = None,
    ) -> AsyncGenerator[None]:
        """Context manager for displaying animation during async operations."""
        ...
        yield  # pragma: no cover - makes this a valid generator

    # -- status & stats ------------------------------------------------------

    @abstractmethod
    async def set_status(
        self,
        status: str | None,
        duration: float | None = None,
    ) -> None:
        """Set the status line, with an optional flash duration. Pass
        `duration` to show `status` as a flash that reverts after N seconds."""
        ...

    @abstractmethod
    def refresh_stats(self) -> None:
        """Re-read every stat and redraw. Sync, not async: an owner calls it
        from a config observer or a timer tick, and a redraw should never be
        something the caller has to await."""
        ...

    # -- lifecycle -----------------------------------------------------------

    @abstractmethod
    async def start(self) -> None:
        """Start the interface."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the interface explicitly."""
        ...

    @abstractmethod
    async def wait_until_ready(self) -> None:
        """Wait until the interface is ready to be used."""
        ...

    # -- input (concrete wrapping + abstract hooks) --------------------------

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
        task = asyncio.ensure_future(self._ask_question(question, default))
        self._active_tasks[task] = None
        try:
            return await task
        except asyncio.CancelledError:
            raise UserCancel from None
        finally:
            self._active_tasks.pop(task, None)

    @abstractmethod
    async def _ask_question(self, question: str, default: str = "") -> str: ...

    async def ask_choice(
        self, question: str, choices: Iterable[str], add_cancel: bool = True
    ) -> int:
        """Ask a multiple-choice question, returns the index for the selected
        option (starting at 0). The prompt-wait is a cancellable like any
        other (see ask_question for the full why): Esc during a choice is
        translated to UserCancel at the boundary, i.e. the same control flow
        as picking the appended "Cancel processing" item - call sites handle
        both identically. The answer is echoed via `print`, so it lands in
        the caller's own scope (e.g. inside a tool's group) rather than
        always at the root."""
        choices_list = list(choices)
        if add_cancel:
            choices_list.append("Cancel processing")

        task = asyncio.ensure_future(self._ask_choice(question, choices_list))
        self._active_tasks[task] = None
        try:
            choice_index = await task
        except asyncio.CancelledError:
            raise UserCancel from None
        finally:
            self._active_tasks.pop(task, None)
        await self.print(choices_list[choice_index], prefix=question)
        if add_cancel and choice_index == len(choices_list) - 1:
            raise UserCancel()
        return choice_index

    @abstractmethod
    async def _ask_choice(self, question: str, choices: list[str]) -> int: ...
