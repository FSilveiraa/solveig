"""The web frontend: a headless SolveigInterface that speaks the event bus.

A browser is across a network boundary, so the terminal's "mount a widget and
mutate it in place" has no direct meaning here. `WebInterface` is the same
seam from the app's side: it implements `SolveigInterface` like the TUI does,
but every verb's *job* is to serialize itself into an `EventStream` event the
browser renders. The handle a verb returns (`add_message` -> `MessageBox`,
`add_text_box` -> `TextBox`) is a thin object that emits the matching update
event; there is no in-process widget behind it.

Three things cross this class, and each is handled honestly:

- **drawing** — `print`, `add_message`, boxes, status, stats all become events.
- **input** — `ask_question`/`ask_choice` publish a prompt event and then
  `await` a future the HTTP layer resolves with the user's answer. This is the
  one verb whose shape is genuinely cross-process, and it is exactly what the
  (broken-open) contract is for: a blocking wait is implemented by awaiting
  the answer channel, not by reading a keyboard.
- **actions** — the closures `SessionDisplay` builds over a message are not
  serializable, so `add_message` keeps them keyed by a web id and the browser
  POSTs back which action to run. The closure it invokes is the real one; the
  browser never learns what an edit or a branch is.

The `EventStream` lives here (constructed by the interface, not injected), and
the BlackSheep server in `server.py` reads from it and routes input back. This
class knows nothing about HTTP; the server knows nothing about display verbs.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from solveig.interface.base import (
    DiffBox,
    Level,
    MessageActions,
    MessageBox,
    Role,
    SolveigInterface,
    Stat,
    TextBox,
    TreeBox,
)
from solveig.todo import TodoItem
from solveig.utils.file import FileMetadata
from solveig.utils.misc import get_language

from config import SolveigConfig
from .bus import EventStream

if TYPE_CHECKING:
    from os import PathLike

    import uvicorn

    from solveig.pending.user_message_queue import UserMessageQueue

#: How a Level becomes something a browser can style. The TUI picks an emoji
#: prefix; the web picks a CSS class. Same decision, different frontend.
_LEVEL_CLASS = {
    Level.TEXT: "",
    Level.INFO: "info",
    Level.WARNING: "warning",
    Level.ERROR: "error",
    Level.SUCCESS: "success",
}


def _metadata_jsonable(metadata: FileMetadata) -> dict[str, Any]:
    """The parts of FileMetadata a browser tree needs, as plain JSON.

    A browser cannot import `FileMetadata` (nor should it), and the dataclass
    carries fields (owner, group, names) that are terminal display trivia.
    Only shape, size and depth-tell the client matter - the same reduction a
    `TreeDisplay` performs on its own side. `listing` recurses so the whole
    tree travels in one event (lazy expansion is then a client-side choice).
    """
    return {
        "path": metadata.path,
        "is_directory": metadata.is_directory,
        "size": metadata.size,
        "line_count": metadata.line_count,
        "listing": {
            name: _metadata_jsonable(sub)
            for name, sub in (metadata.listing or {}).items()
        },
    }


def _dump_metadata(metadata: FileMetadata) -> dict[str, Any]:
    return _metadata_jsonable(metadata)


# --------------------------------------------------------------------------- #
# Box handles — thin objects that emit update events.                          #
# --------------------------------------------------------------------------- #


class _WebTextBox(TextBox):
    def __init__(self, stream: EventStream, box_id: int) -> None:
        self._stream = stream
        self._id = box_id

    async def append(self, text: str) -> None:
        self._stream.publish(
            {"type": "textbox_update", "id": self._id, "op": "append", "text": text}
        )

    async def clear(self) -> None:
        self._stream.publish({"type": "textbox_update", "id": self._id, "op": "clear"})

    async def replace(self, text: str) -> None:
        self._stream.publish(
            {"type": "textbox_update", "id": self._id, "op": "replace", "text": text}
        )


class _WebDiffBox(DiffBox):
    def __init__(self, stream: EventStream, box_id: int) -> None:
        self._stream = stream
        self._id = box_id

    async def replace(self, old_content: str, new_content: str) -> None:
        self._stream.publish(
            {
                "type": "diff_replace",
                "id": self._id,
                "old": old_content,
                "new": new_content,
            }
        )


class _WebTreeBox(TreeBox):
    def __init__(self, stream: EventStream, box_id: int) -> None:
        self._stream = stream
        self._id = box_id

    async def replace(self, metadata: FileMetadata) -> None:
        self._stream.publish(
            {
                "type": "tree_replace",
                "id": self._id,
                "metadata": _dump_metadata(metadata),
            }
        )

    async def refresh(self) -> None:
        # The tree is drawn from metadata we already sent; an out-of-band
        # mutation redraws the same metadata, so for the browser this is a push
        # of "the client's copy is stale" and it re-renders what it holds.
        self._stream.publish({"type": "tree_refresh", "id": self._id})


class _WebMessageBox(MessageBox):
    def __init__(self, stream: EventStream, box_id: int) -> None:
        self._stream = stream
        self._id = box_id

    async def replace(self, text: str) -> None:
        self._stream.publish({"type": "message_replace", "id": self._id, "text": text})

    async def remove(self) -> None:
        self._stream.publish({"type": "message_remove", "id": self._id})


class _WebReasoningBox(MessageBox):
    def __init__(self, stream: EventStream, box_id: int) -> None:
        self._stream = stream
        self._id = box_id

    async def replace(self, text: str) -> None:
        self._stream.publish(
            {"type": "reasoning_replace", "id": self._id, "text": text}
        )

    async def remove(self) -> None:
        self._stream.publish({"type": "reasoning_remove", "id": self._id})


# --------------------------------------------------------------------------- #
# WebInterface                                                                #
# --------------------------------------------------------------------------- #


@dataclass
class _WebState:
    """The bus and registries a root owns and every group under it reads.

    ONE object rather than seven fields, because a group reaches all of it the
    same way (`self.root._state`) and there is nothing to copy or keep in step.
    `default_factory` throughout: as bare class attributes these would be
    SHARED by every root ever built.
    """

    #: The fan-out to open browsers. Injectable, so a test or the demo harness
    #: can watch what a run emits.
    stream: EventStream = field(default_factory=EventStream)
    #: Ids for boxes, messages, groups and prompts alike - one counter, so
    #: nothing this interface mints can collide with anything else it minted.
    ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))
    #: Message id -> the real closures. The browser POSTs back a NAME, which is
    #: resolved against this.
    message_actions: dict[int, MessageActions] = field(default_factory=dict)
    stats: dict[str, Stat] = field(default_factory=dict)
    #: Prompt id -> the future `ask_*` is waiting on, resolved by the HTTP layer.
    pending: dict[str, asyncio.Future[str]] = field(default_factory=dict)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    status: str | None = None
    server: uvicorn.Server | None = None


class WebInterface(SolveigInterface):
    """A SolveigInterface whose "screen" is every open browser.

    Constructor-free beyond the bus and a counter - a web client is never in
    a process that wants an object it cannot reach, so there is nothing to
    configure. The group stack is internal state below.
    """

    if TYPE_CHECKING:
        # The base can only promise the protocol; inside this frontend the root
        # is always a WebInterface, which is what makes `self.root._state`
        # typecheck. Declaration only - the runtime property is the base's.
        @property
        def root(self) -> WebInterface: ...

    #: The group this interface draws into; None on the root. Every event it
    #: emits carries it, so two parallel groups each tag their own.
    _group_id: int | None = None

    def __init__(
        self,
        config: SolveigConfig,
        user_message_queue: UserMessageQueue,
        stream: EventStream | None = None,
    ) -> None:
        super().__init__(config, user_message_queue)
        self._state = _WebState(stream=stream or EventStream())

    # -- id + emit helpers ---------------------------------------------------

    @property
    def stream(self) -> EventStream:
        """The one bus, wherever it is asked for. Derived rather than copied
        into each group: there is nothing to keep in step, and `server.py`
        reads it off whichever interface it was handed."""
        return self.root._state.stream

    def _emit(self, event: dict[str, Any]) -> None:
        """The one emission path, root and group alike.

        A group tags every event it emits with its own id, and the root's is
        None so its events carry none. The tag comes from the OBJECT doing the
        emitting, never from a stack — a group is something you write to, not a
        position you happened to open last.
        """
        if self._group_id is not None:
            event = {**event, "group": self._group_id}
        self.root._state.stream.publish(event)

    def _emit_at_root(self, event: dict[str, Any]) -> None:
        """Emit WITHOUT this interface's group tag.

        For the app-wide surfaces: a status change or a stats redraw is not
        part of whatever group happened to raise it, and a browser that saw one
        tagged would file it under that group. The base already routes those
        verbs to the root, so this only matters for `add_stat`'s own event.
        """
        self.root._state.stream.publish(event)

    # -- text ----------------------------------------------------------------

    async def print(
        self,
        text: str,
        level: Level = Level.TEXT,
        *,
        prefix: str | None = None,
    ) -> None:
        self._emit(
            {
                "type": "print",
                "text": text,
                "level": level.name,
                "cls": _LEVEL_CLASS.get(level, ""),
                "prefix": prefix,
            }
        )

    # -- transcript verbs ----------------------------------------------------

    async def add_message(
        self, text: str, role: Role, actions: MessageActions
    ) -> MessageBox:
        mid = next(self.root._state.ids)
        self.root._state.message_actions[mid] = actions
        self._emit(
            {
                "type": "message",
                "id": mid,
                "role": role.value,
                "text": text,
                "actions": [
                    name
                    for name, fn in (
                        ("edit", actions.edit),
                        ("retry", actions.retry),
                        ("delete", actions.delete),
                        ("branch", actions.branch),
                    )
                    if fn is not None
                ],
            }
        )
        return _WebMessageBox(self.stream, mid)

    async def add_reasoning(self, text: str) -> MessageBox:
        rid = next(self.root._state.ids)
        self._emit({"type": "reasoning", "id": rid, "text": text})
        return _WebReasoningBox(self.stream, rid)

    # -- complex display -----------------------------------------------------

    async def display_file_metadata(
        self,
        abs_path: str | PathLike,
        metadata: FileMetadata | None = None,
        prefix: str | None = None,
        is_directory: bool = False,
    ) -> None:
        self._emit(
            {
                "type": "file_metadata",
                "path": str(metadata.path if metadata else abs_path),
                "prefix": prefix,
            }
        )

    async def display_todos(self, todos: list[TodoItem]) -> None:
        self._emit(
            {
                "type": "todos",
                "todos": [
                    {
                        "content": t.content,
                        "status": t.status.value,
                        "marker": t.status.marker,
                    }
                    for t in todos
                ],
            }
        )

    # -- add (returns object) ------------------------------------------------

    async def add_diff_box(
        self,
        old_content: str,
        new_content: str,
        title: str | None = None,
    ) -> DiffBox:
        box_id = next(self.root._state.ids)
        self._emit(
            {
                "type": "diff",
                "id": box_id,
                "title": title,
                "old": old_content,
                "new": new_content,
            }
        )
        return _WebDiffBox(self.stream, box_id)

    async def add_tree_box(
        self,
        metadata: FileMetadata,
        title: str | None = None,
        display_metadata: bool = False,
    ) -> TreeBox:
        box_id = next(self.root._state.ids)
        self._emit(
            {
                "type": "tree",
                "id": box_id,
                "title": title,
                "metadata": _dump_metadata(metadata),
            }
        )
        return _WebTreeBox(self.stream, box_id)

    async def add_text_box(
        self,
        text: str,
        title: str | None = None,
        language: str | None = None,
        collapsed: bool = False,
    ) -> TextBox:
        box_id = next(self.root._state.ids)
        language_name = get_language(language.lstrip(".")) if language else None
        self._emit(
            {
                "type": "textbox",
                "id": box_id,
                "title": title,
                "text": text,
                "language": language_name,
                "collapsed": collapsed,
            }
        )
        return _WebTextBox(self.stream, box_id)

    def _add_stat(
        self,
        label: str,
        read: Callable[[], Any],
        on_click: Callable[[], Awaitable[None]] | None = None,
        render: Callable[[Any], str] | None = None,
    ) -> Stat:
        stat = _WebStat(label, read, on_click, render, self)
        self.root._state.stats[label] = stat
        self._emit_at_root({"type": "stats", "stats": self._stats_json()})
        return stat

    def _stats_json(self) -> list[dict[str, Any]]:
        return [
            {"label": s.label, "text": s.text} for s in self.root._state.stats.values()
        ]

    # -- groups --------------------------------------------------------------

    @asynccontextmanager
    async def with_group(
        self, title: str, collapse_when_done: bool = True
    ) -> AsyncGenerator[SolveigInterface, Any]:
        group = _WebGroup(self, title, collapse_when_done)
        async with group:
            # Membership for exactly the group's lifetime, which is what lets
            # `self.cancel_task()` reach work started inside it.
            self._children.add(group)
            try:
                yield group
            finally:
                self._children.discard(group)

    # -- status & stats ------------------------------------------------------

    async def _set_status(
        self,
        status: str | None,
        duration: float | None = None,
    ) -> None:
        self.root._state.status = status
        self._emit_at_root({"type": "status", "status": status, "duration": duration})

    def _refresh_stats(self) -> None:
        self._emit_at_root({"type": "stats", "stats": self._stats_json()})

    # -- animation -----------------------------------------------------------

    @asynccontextmanager
    async def _animate(
        self,
        status: str = "Processing",
        final_status: str | None = None,
        timeout: float | None = None,
    ):
        await self.set_status(status)
        try:
            yield
        finally:
            await self.set_status(final_status)

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Serve the HTTP app until `stop()`. Occupies the process (awaited in
        the foreground by run_async) exactly as Textual's event loop does."""
        from .server import serve

        await serve(
            self, self.config.interface.web.host, self.config.interface.web.port
        )

    async def stop(self) -> None:
        if self.root._state.server is not None:
            self.root._state.server.should_exit = True

    async def wait_until_ready(self) -> None:
        await self.root._state.ready.wait()

    async def _mark_ready(self, *_: Any, **__: Any) -> None:
        """BlackSheep `on_start` hook: the server is accepting connections."""
        self.root._state.ready.set()

    async def _mark_stopped(self, *_: Any, **__: Any) -> None:
        self.root._state.ready.clear()

    # -- input ---------------------------------------------------------------

    async def _ask_question(self, question: str, default: str = "") -> str:
        prompt_id = f"q{next(self.root._state.ids)}"
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self.root._state.pending[prompt_id] = future
        self._emit(
            {
                "type": "ask_question",
                "id": prompt_id,
                "question": question,
                "default": default,
            }
        )
        try:
            return await future
        finally:
            self.root._state.pending.pop(prompt_id, None)

    async def _ask_choice(self, question: str, choices: list[str]) -> int:
        prompt_id = f"c{next(self.root._state.ids)}"
        future = asyncio.get_running_loop().create_future()
        self.root._state.pending[prompt_id] = future
        self._emit(
            {
                "type": "ask_choice",
                "id": prompt_id,
                "question": question,
                "choices": choices,
            }
        )
        try:
            answer = await future
            return int(answer) if answer.isdigit() else choices.index(answer)
        finally:
            self.root._state.pending.pop(prompt_id, None)

    # -- the HTTP-facing actions (called by server.py) -----------------------

    def answer_prompt(self, prompt_id: str, value: str) -> bool:
        """Resolve a pending ask with the user's answer. False if unknown/idle."""
        future = self.root._state.pending.pop(prompt_id, None)
        if future is None or future.done():
            return False
        future.set_result(value)
        return True

    def cancel_prompt(self, prompt_id: str) -> bool:
        future = self.root._state.pending.pop(prompt_id, None)
        if future is None or future.done():
            return False
        future.cancel()
        return True

    async def _resolve_action(
        self, message_id: int, action: str, text: str | None
    ) -> bool:
        actions = self.root._state.message_actions.get(message_id)
        if actions is None:
            return False
        if action == "edit" and actions.edit is not None and text is not None:
            await actions.edit(text)
            return True
        if action == "retry" and actions.retry is not None:
            await actions.retry()
            return True
        if action == "delete" and actions.delete is not None:
            await actions.delete()
            return True
        if action == "branch" and actions.branch is not None:
            await actions.branch()
            return True
        return False

    def retire_message(self, message_id: int) -> None:
        """Drop a message's action closures (its widget was removed)."""
        self.root._state.message_actions.pop(message_id, None)


class _WebStat(Stat):
    """A Stat that republishes the bar when refreshed over the wire.

    `Stat.refresh()` is a no-op by default because a headless interface has
    nothing to redraw; here it does - every stat's value travels to the bus.
    """

    def __init__(
        self,
        label: str,
        read: Callable[[], Any],
        on_click: Callable[[], Awaitable[None]] | None,
        render: Callable[[Any], str] | None,
        interface: WebInterface,
    ) -> None:
        super().__init__(label, read, on_click, render)
        self._interface = interface

    def refresh(self) -> None:
        self._interface.refresh_stats()


class _WebGroup(WebInterface):
    """One group in the transcript: the same interface, tagging its id.

    It borrows nothing. The bus, the id counter and every registry are reached
    through `root`, so there is no field list to keep in step - and the two
    entries the previous hand-copying version got wrong (`_status` and
    `_server`, both snapshots of values the root reassigns) cannot be written.
    What it stores is only what it IS: who contains it, what it is called, and
    its own id.

    It announces itself, too: `group_start` on entry and `group_end` on exit,
    emitted THROUGH THE PARENT so the event that opens a group carries the
    enclosing group's tag rather than its own.
    """

    def __init__(
        self, parent: WebInterface, title: str, collapse_when_done: bool = True
    ) -> None:
        # The BASE constructor, not WebInterface's - that one mints a fresh bus
        # and a fresh registry the root's `_resolve_action` would never consult.
        SolveigInterface.__init__(self, parent.config, parent.user_message_queue)
        self._parent = parent
        self._title = title
        self._collapse_when_done = collapse_when_done
        self._group_id = next(self.root._state.ids)

    async def __aenter__(self) -> _WebGroup:
        assert isinstance(self._parent, WebInterface)
        # `parent` is WHO CONTAINS this group, so nesting survives events
        # interleaving with siblings - it is never inferred from arrival order.
        self._parent._emit(
            {
                "type": "group_start",
                "id": self._group_id,
                "title": self._title,
                "parent": self._parent._group_id,
                "collapse_when_done": self._collapse_when_done,
            }
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        assert isinstance(self._parent, WebInterface)
        self._parent._emit({"type": "group_end", "id": self._group_id})
