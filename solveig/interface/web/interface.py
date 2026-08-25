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

from ...config import SolveigConfig
from .bus import EventStream

if TYPE_CHECKING:
    from os import PathLike

    import uvicorn

    from solveig.user_message_queue import UserMessageQueue

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


class WebInterface(SolveigInterface):
    """A SolveigInterface whose "screen" is every open browser.

    Constructor-free beyond the bus and a counter - a web client is never in
    a process that wants an object it cannot reach, so there is nothing to
    configure. The group stack is internal state below.
    """

    def __init__(
        self,
        config: SolveigConfig,
        user_message_queue: UserMessageQueue,
        stream: EventStream | None = None,
    ) -> None:
        super().__init__(config, user_message_queue)
        self.stream = stream or EventStream()
        self._ids: itertools.count[int] = itertools.count(1)
        self._message_actions: dict[int, MessageActions] = {}
        self._stats: dict[str, Stat] = {}
        #: A pending prompt, awaited by ask_question/ask_choice and resolved by
        #: the HTTP layer when the browser answers.
        self._pending: dict[str, asyncio.Future[str]] = {}
        #: The group THIS interface represents. None for the root; a `_WebGroup`
        #: sets it to its own id, so a `with_group` called HERE declares that as
        #: its `parent`. It is the object's identity, never a stack position.
        self._group_id: int | None = None
        self._status: str | None = None
        self._ready = asyncio.Event()
        self._server: uvicorn.Server | None = None

    # -- id + emit helpers ---------------------------------------------------

    def _emit(self, event: dict[str, Any]) -> None:
        # Root-level emit: content emitted through the ROOT interface carries no
        # group (it belongs to the transcript top level). Content drawn through
        # a group reaches a `_WebGroup`, which pins its own id instead of using
        # this path. No stack, no "innermost" — a group is an object you write
        # to, never a position you happened to open last.
        self.stream.publish(event)

    @asynccontextmanager
    async def _scope(self, title: str, auto_collapse: bool = False):
        gid = next(self._ids)
        # `parent` is the group THIS interface represents — None for the root,
        # this group's own id when `self` is a `_WebGroup`. It is WHO called
        # with_group, not a stack peek, so a group opened inside a group pins
        # its real parent even when sibling frames interleave.
        parent = self._group_id
        self._emit({"type": "group_start", "id": gid, "title": title, "parent": parent})
        try:
            yield gid
        finally:
            self._emit({"type": "group_end", "id": gid})

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
        mid = next(self._ids)
        self._message_actions[mid] = actions
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
        rid = next(self._ids)
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
        box_id = next(self._ids)
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
        box_id = next(self._ids)
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
        box_id = next(self._ids)
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

    def add_stat(
        self,
        label: str,
        get: Callable[[], Any],
        on_click: Callable[[], Awaitable[None]] | None = None,
        render: Callable[[Any], str] | None = None,
    ) -> Stat:
        stat = _WebStat(label, get, on_click, render, self)
        self._stats[label] = stat
        self._emit({"type": "stats", "stats": self._stats_json()})
        return stat

    def _stats_json(self) -> list[dict[str, Any]]:
        return [{"label": s.label, "text": s.text} for s in self._stats.values()]

    # -- groups --------------------------------------------------------------

    @asynccontextmanager
    async def with_group(
        self, title: str, auto_collapse: bool = False
    ) -> AsyncGenerator[SolveigInterface, Any]:
        async with self._scope(title, auto_collapse) as gid:
            # Scoped child: same bus, tagged with this group. Root-level verbs
            # (status, stats, prompts) stay on the root.
            child = _WebGroup(self, gid)
            yield child

    # -- status & stats ------------------------------------------------------

    async def set_status(
        self,
        status: str | None,
        duration: float | None = None,
    ) -> None:
        self._status = status
        self._emit({"type": "status", "status": status, "duration": duration})

    def refresh_stats(self) -> None:
        self._emit({"type": "stats", "stats": self._stats_json()})

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
        if self._server is not None:
            self._server.should_exit = True

    async def wait_until_ready(self) -> None:
        await self._ready.wait()

    async def _mark_ready(self, *_: Any, **__: Any) -> None:
        """BlackSheep `on_start` hook: the server is accepting connections."""
        self._ready.set()

    async def _mark_stopped(self, *_: Any, **__: Any) -> None:
        self._ready.clear()

    # -- input ---------------------------------------------------------------

    async def _ask_question(self, question: str, default: str = "") -> str:
        prompt_id = f"q{next(self._ids)}"
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending[prompt_id] = future
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
            self._pending.pop(prompt_id, None)

    async def _ask_choice(self, question: str, choices: list[str]) -> int:
        prompt_id = f"c{next(self._ids)}"
        future = asyncio.get_running_loop().create_future()
        self._pending[prompt_id] = future
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
            self._pending.pop(prompt_id, None)

    # -- the HTTP-facing actions (called by server.py) -----------------------

    def answer_prompt(self, prompt_id: str, value: str) -> bool:
        """Resolve a pending ask with the user's answer. False if unknown/idle."""
        future = self._pending.pop(prompt_id, None)
        if future is None or future.done():
            return False
        future.set_result(value)
        return True

    def cancel_prompt(self, prompt_id: str) -> bool:
        future = self._pending.pop(prompt_id, None)
        if future is None or future.done():
            return False
        future.cancel()
        return True

    async def _resolve_action(
        self, message_id: int, action: str, text: str | None
    ) -> bool:
        actions = self._message_actions.get(message_id)
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
        self._message_actions.pop(message_id, None)


class _WebStat(Stat):
    """A Stat that republishes the bar when refreshed over the wire.

    `Stat.refresh()` is a no-op by default because a headless interface has
    nothing to redraw; here it does - every stat's value travels to the bus.
    """

    def __init__(
        self,
        label: str,
        get: Callable[[], Any],
        on_click: Callable[[], Awaitable[None]] | None,
        render: Callable[[Any], str] | None,
        interface: WebInterface,
    ) -> None:
        super().__init__(label, get, on_click, render)
        self._interface = interface

    def refresh(self) -> None:
        self._interface.refresh_stats()


class _WebGroup(WebInterface):
    """The child `with_group` yields: same bus, events tagged with one group.

    Root-level verbs (status, stats, prompts, lifecycle) delegate back to the
    root; everything that draws goes through the interface's emit path, which
    tags with the group id.
    """

    def __init__(self, root: WebInterface, group_id: int) -> None:
        # Share the root's bus, id counter and registries; do NOT re-run
        # WebInterface.__init__, which would mint a fresh counter and a fresh
        # _message_actions the root's _resolve_action never consults. That
        # isolation is the bug the wire _WireGroup's seam comment names: a
        # message added inside the group would register its action closure in a
        # dict the top of the app never reads, and its fresh id counter would
        # collide with the root's. A group is a SCOPED VIEW of the root's
        # screen, not a second interface with its own state.
        self._root = root
        self._group_id = group_id
        self._ids = root._ids
        self._message_actions = root._message_actions
        self._stats = root._stats
        self._status = root._status
        self._server = root._server
        self._ready = root._ready
        # Cancellation is shared too: a cancel issued anywhere must reach work
        # started inside a group (same reasoning as the wire _WireGroup).
        self._active_tasks = root._active_tasks
        self.stream = root.stream
        self.user_message_queue = root.user_message_queue

    def _emit(self, event: dict[str, Any]) -> None:
        # This group's id is forced, not read off a shared stack: a nested or
        # sibling caller holds THIS object, so ITS id travels. A `with_group`
        # called on this group then declares `self._group_id` as the child's
        # parent — object identity, the wire's `parent` linkage.
        event = {**event, "group": self._group_id}
        self.stream.publish(event)

    async def set_status(self, status, duration=None) -> None:
        await self._root.set_status(status, duration)

    def refresh_stats(self) -> None:
        self._root.refresh_stats()

    def add_stat(self, *args) -> Stat:
        return self._root.add_stat(*args)

    async def _ask_question(self, question, default="") -> str:
        return await self._root._ask_question(question, default)

    async def _ask_choice(self, question, choices) -> int:
        return await self._root._ask_choice(question, choices)

    async def start(self) -> None:
        await self._root.start()

    async def stop(self) -> None:
        await self._root.stop()
