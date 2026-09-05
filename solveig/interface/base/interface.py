"""The display protocol for Solveig's frontends.

`SolveigInterface` is the contract that any UI (TUI, web, desktop GUI, headless logger,
voice bot) implements:
render (`print`, `display_*`, `add_*`), ask (`ask_*`), scope (`with_group`),
work (`with_cancellable`), and theming. It also carries two
concerns every interactive frontend shares — the user-message queue (the
interface's output channel for typed input) and cancellation
(`with_cancellable` + the `_tasks`/`_children` tree + `cancel_task`). Command
dispatch lives OUTSIDE the interface — the queue's prompt gate routes
/commands before insertion.

Naming conventions:
- `print`   — text output, void
- `add_`    — returns a handle the caller keeps (add_text_box → TextBox,
              add_tree_box → TreeBox, add_message → MessageBox, add_stat → Stat)
- `with_`   — async context manager (with_group, with_cancellable)
- `display_`— draws and hands back nothing (display_todos, display_file_metadata)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, nullcontext
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from anyio import CancelScope

from solveig.config import SolveigConfig
from solveig.exceptions import UserCancel
from solveig.interface.base.actions import MessageActions, Role
from solveig.interface.base.widgets import DiffBox, MessageBox, TextBox, TreeBox
from solveig.todo import TodoItem
from solveig.utils.file import FileMetadata

if TYPE_CHECKING:
    from os import PathLike

    from solveig.pending.user_message_queue import UserMessageQueue


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

    Holds NO value: `read` PULLS from the live source, so `config.api.model`
    stays the single home and there is nothing to drift or re-sync. Storing the
    value instead would put a copy of the process cwd beside the process cwd
    (`Path`), and would make a two-source cell inexpressible - `Context` reads
    usage AND `api.max_context`, each with its own trigger, and a stored value
    would force whichever one changed to also know the other. Pulling is also
    self-healing: a blanket `refresh_stats()` re-reads everything, where stored
    values would redraw stale copies.

    Named `read`, not `get`: it is what the frontend does to the source, and a
    verb-shaped name for a plain field reads like an action the caller performs.

    `on_click` takes nothing: whatever it needs (a config, an interface to
    prompt on) its owner closed over when registering. That is what keeps the
    behaviour of a config stat inside the config module - the widget calls a
    callable and never learns what a config is.
    """

    def __init__(
        self,
        label: str,
        read: Callable[[], Any],
        on_click: Callable[[], Awaitable[None]] | None = None,
        render: Callable[[Any], str] | None = None,
    ) -> None:
        self.label = label
        self.read = read
        self.on_click = on_click
        #: Value -> text. The OWNER knows a context stat reads "12/128k" or
        #: "Unlimited"; the frontend only knows where to put the result.
        self.render = render

    @property
    def text(self) -> str:
        value = self.read()
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


class SolveigInterface(ABC):
    """The display protocol any UI implementation (terminal, web, desktop,
    headless mock) provides: render, ask, scope, status/animation, theme.

    It holds no conversation, and none of its verbs names a message. Everything
    a frontend needs to draw arrives as an argument - text, a role, the actions
    a message offers - so implementing one requires knowing nothing about
    pydantic-ai's message model, and the observer on the other side of this
    protocol can be swapped without a frontend noticing.

    Two cross-cutting concerns are protocol-level ON PURPOSE (every UI with
    user input shares them, so a frontend never re-implements them):

    - **User-message queue** (`user_message_queue`) - the interface's output
      channel for typed input. The interface `put`s; the queue's prompt gate
      decides what actually lands (prompts vs swallowed /commands).
    - **Cancellation** (`with_cancellable`, the `_tasks`/`_children` tree,
      `cancel_task`, `get_active_tasks`) - every interactive UI has both a
      targeted cancel (a button) and a global untargeted one (Esc, Ctrl+C), so
      the registry and the verb live here. Work belongs to the interface it
      started on, so cancelling is addressed by WHICH ONE you call it on.

    What is NOT here: prompt serialization policy (each frontend's own,
    e.g. the CLI's `_choice_lock`) and command dispatch (the queue gate's).
    """

    def __init__(
        self, config: SolveigConfig, user_message_queue: UserMessageQueue
    ) -> None:
        self.config: SolveigConfig = config
        self.user_message_queue: UserMessageQueue = user_message_queue
        #: Cancellable work started on THIS interface. A group owns its own,
        #: so cancelling addresses a receiver instead of searching one shared
        #: list for "whose is this".
        self._tasks: set[CancelScope] = set()
        #: The interface this one was opened under; None on a root. The only
        #: group fact the contract keeps, because the contract USES it - `root`
        #: derives from it and the cancellation tree hangs off it. What a group
        #: is CALLED is not here: a frontend already holds the group as `self`,
        #: so it can use its own title, its own id, or its own widget, and the
        #: contract has no business guessing which of those identifies it.
        self._parent: SolveigInterface | None = None
        #: Groups open under this one. `with_group` adds on entry and discards
        #: in its teardown, so membership is exactly a group's lifetime — which
        #: is what lets `cancel_task()` reach into it.
        self._children: set[SolveigInterface] = set()

    @property
    def root(self) -> SolveigInterface:
        return self._parent.root if self._parent is not None else self

    # -- cancellation (protocol-level, concrete) -----------------------------

    def get_active_tasks(self) -> set[CancelScope]:
        """This interface's in-flight work, plus everything running inside the
        groups open under it. Empty is falsy, so
        `if interface.get_active_tasks():` is still the busy check.

        NOTE: a "task" here is a unit of work the user started, and the handle
        for it is the `CancelScope` that block runs under - NOT an
        `asyncio.Task`. The protocol keeps the domain word deliberately: what a
        frontend needs to know is that something cancellable is in flight, and
        which async primitive expresses that is not its business.

        NOTE: a SET, not an ordered mapping. Registration order carries no
        meaning, and any rule that read one would be inferring which task the
        user meant instead of being told."""
        return self._tasks | {
            task for child in self._children for task in child.get_active_tasks()
        }

    def cancel_task(self, *tasks: CancelScope) -> bool:
        """Cancel the given tasks, or everything under THIS interface when none
        are given. True if anything was actually cancelled.

        NOTE: the address is the RECEIVER. `group.cancel_task()` stops that
        group's work; `root.cancel_task()` stops the run. Nothing is inferred -
        not from nesting depth, not from registration order, not by searching a
        shared list. Same rule `with_group` follows: the object you are holding
        IS the thing you are talking about.

        Cancellation reaches DOWNWARD only. An interface cancels itself and the
        groups inside it, and can never reach its parent - a tool has no
        business stopping what contains it.

        NOTE: which task an untargeted keystroke means is the frontend's own
        business, because only it knows what has focus. This does not guess."""
        cancelled = False
        for scope in tasks or self.get_active_tasks():
            if not scope.cancel_called:
                scope.cancel()
                cancelled = True
        return cancelled

    @asynccontextmanager
    async def _cancellable(
        self, animation: AbstractAsyncContextManager[Any] | None = None
    ) -> AsyncGenerator[CancelScope]:
        """The ONE place a block becomes cancellable work on this interface:
        open a scope, register it, run under it, unregister, and report a
        cancel as `UserCancel`. `with_cancellable` and both prompts are this
        with and without an animation, so the rules below are written once.

        `animation` is held open AROUND the scope rather than around this whole
        block, and that interleaving is load-bearing in both directions.
        Registration comes FIRST because a frontend deciding whether to offer a
        cancel hint reads `get_active_tasks()` while starting the animation -
        registering after would make the hint silently never appear. The scope
        is entered INSIDE it because a cancelled scope raises at every
        subsequent await within it: were the animation's teardown inside the
        scope, its own `await set_status(...)` would be cancelled too and the
        status line would keep showing the cancelled work's status forever.
        Two nested context managers cannot express that, which is why the
        animation arrives as an argument instead of wrapping the call.

        None for a prompt. A prompt is a WAIT, not work: it is already on
        screen saying what it is, and a spinner over it would claim something
        is running.
        """
        scope = CancelScope()
        # On THIS interface, not the root's: work opened inside a group is that
        # group's, so `group.cancel_task()` reaches it.
        self._tasks.add(scope)
        try:
            async with animation if animation is not None else nullcontext():
                with scope:
                    yield scope
        finally:
            self._tasks.discard(scope)
        if scope.cancel_called:
            raise UserCancel()

    @asynccontextmanager
    @abstractmethod
    async def _animate(
        self,
        status: str = "Processing",
        final_status: str | None = None,
        timeout: float | None = None,
    ) -> AsyncGenerator[None]:
        """Context manager for displaying animation during async operations.

        NOTE: no cancel-hint argument. A frontend that wants to say how to stop
        the work reads `get_active_tasks()` - registration is the fact, and the
        wording is the frontend's own business."""
        yield  # pragma: no cover - makes this a valid generator

    def with_cancellable(
        self,
        status: str,
        final_status: str | None = None,
        timeout: float | None = None,
    ) -> AbstractAsyncContextManager[CancelScope]:
        """Run this BLOCK as busy, user-cancellable work: show `status` while it
        runs, and let a cancel stop it wherever it has got to.

        The cancellable unit is the block, not a coroutine handed in - so the
        consent prompt, the setup and the read loop inside it are all covered,
        and a caller no longer packages a region of code as an object just to
        have something to hand over. An `anyio.CancelScope` cancels at the next
        checkpoint inside itself and then ABSORBS the CancelledError (calling
        task.uncancel()), so the caller's task survives and this can report the
        cancel as a raised `UserCancel` instead. Same machinery as
        `asyncio.timeout()`, which is a cancel scope carrying a deadline.

        Raising rather than handing back `scope.cancel_called` to check: the
        behaviour you get by writing nothing has to be the safe one. Forget a
        check and execution falls into code that assumes the work happened;
        forget the catch and the turn aborts, which is what a cancel means. It
        also keeps ONE cancellation vocabulary - a cancelled prompt already
        raises UserCancel, and `agent.py` already treats the two as one thing.

        The registration/animation/scope ordering this depends on lives in
        `_cancellable`, along with why it cannot be written as nesting.

        NOTE: what the trigger is CALLED is not protocol. Registering the scope
        already tells the frontend this work is cancellable; how a user reaches
        that - which keystroke, spelled how, or a ✕ button instead - only the
        frontend knows, and only the frontend can keep the name honest.

        NOTE: returns the context manager rather than being one. `_cancellable`
        is the generator; this only decides that work gets an animation and a
        prompt does not.
        """
        return self._cancellable(
            self._animate(status=status, final_status=final_status, timeout=timeout)
        )

    # -- text ----------------------------------------------------------------

    @abstractmethod
    async def print(
        self,
        text: str,
        level: Level = Level.TEXT,
        *,
        prefix: str | None = None,
    ) -> None:
        """Print text with a severity level and optional prefix."""
        ...

    # -- transcript verbs ----------------------------------------------------

    @abstractmethod
    async def add_message(
        self, text: str, role: Role, actions: MessageActions
    ) -> MessageBox:
        """Draw one message and hand back the handle to it.

        Everything needed to draw it arrives here: the TEXT (already decoded -
        a frontend never sees a model message), WHO it is from, and WHAT may be
        done to it. A frontend renders a control per action it was handed and
        decides nothing about which ones exist.

        Restating or removing this message later goes through the returned
        handle, so nothing addresses a message by id and no frontend keeps a
        map of what it drew."""
        ...

    @abstractmethod
    async def add_reasoning(self, text: str) -> MessageBox:
        """Draw the assistant's reasoning and hand back the handle.

        Its own verb rather than a flag on `add_message`, because a frontend
        that cannot tell reasoning apart cannot present it differently, and the
        old protocol's answer to that was `italic=True` - one frontend's styling
        decision made by the caller. Reasoning carries no role and no actions:
        it is not a turn and cannot be edited or retried."""
        ...

    # -- complex display -----------------------------------------------------

    @abstractmethod
    async def display_file_metadata(
        self,
        abs_path: str | PathLike,
        metadata: FileMetadata | None = None,
        prefix: str | None = None,
        is_directory: bool = False,
    ) -> None:
        """Draw one filesystem entry as a header line.

        Takes the metadata as a VALUE: the caller does the filesystem work, because
        reading a `stat` is not a display concern. The glyphs, the separators, which
        fields are worth showing and how long a path may get are all this method's.

        `metadata` is the source of truth for everything it carries — path,
        directory-ness, size, line count. `None` is a real state, not a caller being
        lazy: the entry could not be read, either because it does not exist yet
        (`write` creating one) or because replay is redrawing a call whose file has
        since gone. The remaining arguments are the fallbacks for exactly that case,
        never overrides — when metadata is present it wins.
        """
        ...

    @abstractmethod
    async def display_todos(self, todos: list[TodoItem]) -> None:
        """Draw Solveig's todo list, replacing whatever was shown before.

        Takes the todos as VALUES, not as drawn text. Everything about how a list
        looks is this method's to decide — the ordering glyphs, whether the
        in-progress item is marked with an arrow, a colour, or an animation, whether
        a cancelled item is struck through. `TodoStatus.marker` is available as a
        sensible default and may be ignored entirely.

        NOTE: what the caller still owns is WHAT to show and WHEN. `TodoTool` decides
        the list is worth drawing and hands over the whole of it; it must not decide
        that the current item is an arrow, because a frontend that cannot draw arrows
        would have no way to disagree.
        """
        ...

    # -- add (returns object) ------------------------------------------------

    @abstractmethod
    async def add_diff_box(
        self,
        old_content: str,
        new_content: str,
        title: str | None = None,
    ) -> DiffBox:
        """Add a diff text box the caller can `replace()` with new old/new content.

        How much unchanged context surrounds a hunk is the frontend's own
        setting, not the caller's - a caller asking for a diff has no view on
        how tall it should be."""
        ...

    @abstractmethod
    async def add_tree_box(
        self,
        metadata: FileMetadata,
        title: str | None = None,
        display_metadata: bool = False,
    ) -> TreeBox:
        """Display a directory tree. Returns a TreeBox the caller can
        `replace()` with new metadata.

        `display_metadata` stays a parameter because asking for sizes and line
        counts is content selection - the caller knows whether they are part of
        what it is showing. How deep the tree opens and whether the root starts
        expanded are NOT: they are the frontend's own settings, and the metadata
        handed over is complete either way.

        NOTE: there is no ignore/filter argument, deliberately. Deciding an
        entry should not be seen is a filesystem concern, not a drawing one -
        `Filesystem.read_metadata` prunes it, so what arrives here is already
        everything the caller is willing to show AND to send."""
        ...

    @abstractmethod
    async def add_text_box(
        self,
        text: str,
        title: str | None = None,
        language: str | None = None,
        collapsed: bool = False,
    ) -> TextBox:
        """Add a text block with optional title. Returns a live box the
        caller can append to or replace."""
        ...

    def add_stat(
        self,
        label: str,
        read: Callable[[], Any],
        on_click: Callable[[], Awaitable[None]] | None = None,
        render: Callable[[Any], str] | None = None,
    ) -> Stat:
        """Declare a stat and hand it back. The interface CREATES it, so a
        frontend can return its own subclass carrying whatever it needs to
        place one. The caller keeps the returned object as its handle -
        identity is the object, never a name."""
        return self.root._add_stat(label, read, on_click, render)

    @abstractmethod
    def _add_stat(
        self,
        label: str,
        read: Callable[[], Any],
        on_click: Callable[[], Awaitable[None]] | None = None,
        render: Callable[[Any], str] | None = None,
    ) -> Stat: ...

    # -- groups -------------------------------------------------------------

    @asynccontextmanager
    @abstractmethod
    async def with_group(
        self, title: str, collapse_when_done: bool = True
    ) -> AsyncGenerator[SolveigInterface, Any]:
        """Context manager for grouping related output. Yields a
        SolveigInterface scoped to this group — local calls land inside the
        group; global calls transparently affect the root.

        IMPLEMENTATION CONTRACT: build the child with `_parent` set to `self`,
        add it to `self._children` on entry, and discard it in the teardown that
        already closes the group. That pair is what makes `cancel_task()` and
        `get_active_tasks()` reach work started inside it. What the group is
        called, and anything else that identifies one, is the frontend's to
        keep on its own child.

        NOTE: `auto_collapse` is the caller's INTENT ("folding this away loses
        nothing"), not an instruction. Whether a frontend folds it, and whether
        the user has turned that off, is display policy the frontend reads for
        itself — app code never consults an `interface.*` setting."""
        yield self  # pragma: no cover - makes this a valid generator

    # -- status & stats ------------------------------------------------------

    async def set_status(
        self,
        status: str | None,
        duration: float | None = None,
    ) -> None:
        """Set the status line, with an optional flash duration. Pass
        `duration` to show `status` as a flash that reverts after N seconds."""
        await self.root._set_status(status, duration)

    @abstractmethod
    async def _set_status(
        self,
        status: str | None,
        duration: float | None = None,
    ) -> None: ...

    def refresh_stats(self) -> None:
        """Re-read every stat and redraw. Sync, not async: an owner calls it
        from a config observer or a timer tick, and a redraw should never be
        something the caller has to await."""
        self.root._refresh_stats()

    @abstractmethod
    def _refresh_stats(self) -> None: ...

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

        A user-addressable wait is a registered task like any other: while the
        prompt is open its scope sits in this interface's `_tasks` - so a
        prompt raised inside a group is that group's work - and a targeted
        cancel (a per-prompt ✕) or an untargeted one (Esc -> cancel_task())
        reaches it through the SAME machinery as background work. It goes
        through `_cancellable` WITHOUT an animation: a prompt is a wait, not
        work, and the callers never have to remember to wrap one, because the
        registration lives here at the one seam. A cancelled prompt raises
        UserCancel: to the caller, Esc during a question is the user ANSWERING
        "cancel", identical to picking a Cancel menu item. Prompt CONCURRENCY
        is each frontend's policy (inside its `_ask_*`): a terminal may lock,
        Textual can show stacked prompts, a web UI stacks cards.
        """
        async with self._cancellable():
            answer = await self._ask_question(question, default)
        return answer

    @abstractmethod
    async def _ask_question(self, question: str, default: str = "") -> str:
        """Collect one line of input.

        NOTE: nothing identifies the group here, deliberately. `self` IS the
        group the prompt was raised on, so a frontend that wants to say which
        operation is asking reads whatever identifies one to IT - a title, a
        group id, the widget it drew. Handing one of those down would have been
        both redundant and a guess about which of them matters."""
        ...

    async def ask_choice(
        self, question: str, choices: Iterable[str], add_cancel: bool = True
    ) -> int:
        """Ask a multiple-choice question, returns the index for the selected
        option (starting at 0). The prompt-wait is a cancellable like any
        other (see ask_question for the full why): Esc during a choice raises
        UserCancel, i.e. the same control flow as picking the appended
        "Cancel processing" item - call sites handle both identically. The
        answer is echoed via `print`, so it lands in the caller's own scope
        (e.g. inside a tool's group) rather than always at the root."""
        choices_list = list(choices)
        if add_cancel:
            choices_list.append("Cancel processing")

        async with self._cancellable():
            choice_index = await self._ask_choice(question, choices_list)
        await self.print(choices_list[choice_index], prefix=question)
        if add_cancel and choice_index == len(choices_list) - 1:
            raise UserCancel()
        return choice_index

    @abstractmethod
    async def _ask_choice(self, question: str, choices: list[str]) -> int:
        """Prompt with the given choices (already final), returning the raw
        index. Same as `_ask_question`: `self` is the group, so nothing about
        which group it is travels as an argument."""
        ...
