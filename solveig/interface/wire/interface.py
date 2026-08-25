"""WireInterface — the daemon's broadcast surface over a socket.

`WireInterface` IS the seam the daemon's agent code talks to, exactly as it
talks to a `TerminalInterface` today: one object implementing `SolveigInterface`.
The difference is that its "screen" is every connected client (a second TUI, a
web UI, a telegram bot) — each verb is serialized to a wire frame and broadcast
to all live connections; the box a verb hands back is a `RemoteBox` whose
mutations are the next frame.

The design keeps the wire vocabulary tool-agnostic: a verb names an ABC surface
(`add_text_box(FileMetadata)`), never a tool, so a client renders any stream
forever and needs no plugin config. Adds and boxes cross as ids — the server
mints a global handle id, broadcasts the create verb under it, and the client
keys its own local widget by that id, so a later `invoke` reaches every client
(asherc_aide with the same id).

Consent (`ask_*`) broadcasts to ALL clients, first answer wins; on resolve the
server broadcasts an `ask_resolved` so every client cancels its pending prompt
and shows the winner's answer — the retraction the design log demands.

Frames are type-tagged JSONL; a client MUST ignore unknown types so daemons and
clients at different feature levels share one stream.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from anyio import CancelScope

from solveig.config import SolveigConfig
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
from solveig.interface.wire import protocol
from solveig.todo import TodoItem
from solveig.utils.file import FileMetadata

if TYPE_CHECKING:
    from os import PathLike

    from solveig.user_message_queue import UserMessageQueue

# --------------------------------------------------------------------------- #
# Remote box handles — emit an `invoke` frame for each mutation.               #
# --------------------------------------------------------------------------- #


class _WireBox:
    def __init__(self, server: WireInterface, handle_id: int) -> None:
        self._server = server
        self._id = handle_id

    def _invoke(self, method: str, **args: Any) -> None:
        self._server._publish(
            {"type": "invoke", "id": self._id, "method": method, "args": args}
        )


class _WireTextBox(TextBox, _WireBox):
    async def append(self, text: str) -> None:
        self._invoke("append", text=text)

    async def clear(self) -> None:
        self._invoke("clear")

    async def replace(self, text: str) -> None:
        self._invoke("replace", text=text)


class _WireDiffBox(DiffBox, _WireBox):
    async def replace(self, old_content: str, new_content: str) -> None:
        self._invoke("replace", old=old_content, new=new_content)


class _WireTreeBox(TreeBox, _WireBox):
    async def replace(self, metadata: FileMetadata) -> None:
        self._invoke("replace", metadata=protocol.metadata_to_json(metadata))

    async def refresh(self) -> None:
        self._invoke("refresh")


class _WireMessageBox(MessageBox, _WireBox):
    async def replace(self, text: str) -> None:
        self._invoke("replace", text=text)

    async def remove(self) -> None:
        self._invoke("remove")


# --------------------------------------------------------------------------- #
# WireInterface                                                               #
# --------------------------------------------------------------------------- #


class _WireState:
    server: asyncio.AbstractServer
    # Connected client interfaces
    writers: set[asyncio.StreamWriter] = set()
    # List of published (sent) frames, allowing later replay
    history: list[dict[str, Any]] = []
    # Dict of frame ID to
    message_actions: dict[int, MessageActions] = {}
    ids: itertools.count[int] = itertools.count(1)
    active_tasks: dict[CancelScope, None]
    # TODO should this still exist?
    ready: asyncio.Event = asyncio.Event()


class WireInterface(SolveigInterface):
    """A SolveigInterface whose screen is every connected client socket.

    Starts a server in `start()` that awaits connections; every accepted client
    is added to the broadcast set. Verbs encode to frames and fan out; box
    handles and asks carry server-minted ids.
    """

    def __init__(
        self,
        config: SolveigConfig,
        user_message_queue: UserMessageQueue,
    ) -> None:
        super().__init__(config, user_message_queue)
        self._server: asyncio.AbstractServer | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        #: Every frame published, in order, so a client that connects late is
        #: replayed the same stream a client present from the start saw. This
        #: is how a newcomer catches up: live broadcast starts (membership) but
        #: the `ready` marker, sent after the retained history, is the line
        #: between "replayed" and "live". The web EventStream retains the same
        #: way; both put "replay is not a special path" on the wire.
        self._history: list[dict[str, Any]] = []
        self._widget_id: itertools.count[int] = itertools.count(1)
        # Each message gets an ID which is indexed here against its MessageActions
        # So when "edit" is called on a message, the _MessageBox
        self._message_actions: dict[int, MessageActions] = {}
        # Pending asks awaited by ask_question/ask_choice, keyed by ask id.
        self._asks: dict[int, asyncio.Future[str]] = {}
        # Remote box for each handle we minted.
        self._boxes: dict[int, Any] = {}
        # The group id this interface represents, used for nesting display
        # methods inside groups. None for the root, a `_WireGroup` sets its own id.
        self._group_id: int | None = None
        self._ready = asyncio.Event()

        # Register a callback for whenever any interface config fields change
        # that broadcasts it to all connected interfaces
        @self.config.on_change("interface")
        def on_config_update(_config: SolveigConfig, changed_paths: frozenset[str]):
            self._publish(
                {
                    "type": "config_update",
                    "updates": {
                        # get the string representation of the field, not its object
                        path: _config.get(path, as_field=True)
                        for path in changed_paths
                    },
                }
            )

    # -- transport -----------------------------------------------------------

    async def start(self) -> None:
        """Bind the socket and serve clients until `stop()`."""
        self._server = await asyncio.start_unix_server(
            self._on_connect, self.config.interface.broadcast.socket
        )
        self._ready.set()
        try:
            async with self._server:
                await self._server.serve_forever()
        finally:
            self._ready.clear()

    async def stop(self) -> None:
        # Close every connected client first so their handler loops end, THEN
        # the listening socket. Reversed, `wait_closed()` blocks forever on the
        # accepted connection's handler, which only returns when its client
        # goes away — and this daemon is the one deciding they all go now.
        for writer in list(self._writers):
            writer.close()
        self._writers.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def wait_until_ready(self) -> None:
        await self._ready.wait()

    async def _on_connect(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """A client connected: register, replay, then serve its frames.

        NOTE: a freshly-accepted client is replayed the retained history and a
        `ready` marker BEFORE it is live. The add and the history writes are
        synchronous with no await between them, so a concurrent `_publish`
        cannot interleave: the newcomer reads history-then-ready-then-live, in
        that order. History replay is what makes this race-proof — a frame
        published before this client registered is still in `_history`, so a
        late client misses nothing. The daemon's directed initial-state walk
        (banner, plugins, MCP) remains a future sequencing detail because the
        wire server holds no conversation; parked until the daemon assembler
        exists.
        """
        self._writers.add(writer)
        for frame in self._history:
            writer.write(json.dumps(frame).encode() + b"\n")
        writer.write(json.dumps({"type": "ready"}).encode() + b"\n")
        await writer.drain()
        try:
            while line := await reader.readline():
                frame = json.loads(line)
                await self._on_frame(frame, writer)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self._writers.discard(writer)

    # -- fan-out -------------------------------------------------------------

    def _publish(self, frame: dict[str, Any]) -> None:
        # One emission path. The ONLY thing that tags a frame with a group is a
        # _WireGroup scoped child shadowing this method — the root itself is a
        # clean slate, which is what lets two parallel groups both draw through
        # their own pinned id instead of arguing over a shared stack.
        self._history.append(frame)
        payload = json.dumps(frame) + "\n"
        for writer in list(self._writers):
            try:
                writer.write(payload.encode())
            except (ConnectionError, RuntimeError):
                continue

    async def _flush(self) -> None:
        for writer in list(self._writers):
            try:
                await writer.drain()
            except (ConnectionError, RuntimeError):
                pass

    async def _send_verb(self, verb: str, **args: Any) -> None:
        self._publish({"type": "verb", "verb": verb, "args": args})
        await self._flush()

    def _next_id(self) -> int:
        return next(self._widget_id)

    # -- wire "add" implementation: mint id, broadcast create, return proxy ----

    async def _create_box(self, verb: str, **args: Any) -> int:
        handle_id = self._next_id()
        self._publish({"type": "verb", "verb": verb, "id": handle_id, "args": args})
        await self._flush()
        return handle_id

    # -- inbound: answers, actions, input -------------------------------------

    async def _on_frame(
        self, frame: dict[str, Any], _writer: asyncio.StreamWriter
    ) -> None:
        ftype = frame.get("type")
        if ftype == "answer":
            ask_id = int(frame.get("id", 0))
            future = self._asks.get(ask_id)
            if future is not None and not future.done():
                value = frame.get("value", "")
                future.set_result(value)
                # Retraction: broadcast the winner's answer so every other
                # client cancels its pending prompt and shows it.
                self._publish({"type": "ask_resolved", "id": ask_id, "answer": value})
                await self._flush()
        elif ftype == "input":
            user_message_queue = self.user_message_queue
            if user_message_queue is not None:
                await user_message_queue.put(frame.get("text", ""))
        elif ftype == "action":
            await self._handle_message_action(frame)

    async def _handle_message_action(self, frame: dict[str, Any]) -> None:
        actions = self._message_actions.get(int(frame.get("message_id", 0)))
        if actions is None:
            return
        name = frame.get("action")
        if name == "edit" and actions.edit is not None:
            await actions.edit(frame.get("text", ""))
        elif name == "retry" and actions.retry is not None:
            await actions.retry()
        elif name == "delete" and actions.delete is not None:
            await actions.delete()
        elif name == "branch" and actions.branch is not None:
            await actions.branch()

    # ----------------------------------------------------------------------- #
    # SolveigInterface verbs                                                 #
    # ----------------------------------------------------------------------- #

    async def print(
        self,
        text: str,
        level: Level = Level.TEXT,
        *,
        prefix: str | None = None,
    ) -> None:
        await self._send_verb("print", text=text, level=level.name, prefix=prefix)

    async def add_message(
        self, text: str, role: Role, actions: MessageActions
    ) -> MessageBox:
        message_id = self._next_id()
        self._message_actions[message_id] = actions
        # Same shape as _create_box: the id sits at the TOP of the frame, the
        # display args under `args`, so the client reads one id location.
        self._publish(
            {
                "type": "verb",
                "verb": "add_message",
                "id": message_id,
                "args": {
                    "text": text,
                    "role": role.value,
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
                },
            }
        )
        await self._flush()
        return _WireMessageBox(self, message_id)

    async def add_reasoning(self, text: str) -> MessageBox:
        handle = await self._create_box("add_reasoning", text=text)
        return _WireMessageBox(self, handle)

    async def display_file_metadata(
        self,
        abs_path: str | PathLike,
        metadata: FileMetadata | None = None,
        prefix: str | None = None,
        is_directory: bool = False,
    ) -> None:
        await self._send_verb(
            "display_file_metadata",
            path=str(metadata.path if metadata is not None else abs_path),
            prefix=prefix,
        )

    async def display_todos(self, todos: list[TodoItem]) -> None:
        await self._send_verb(
            "display_todos", todos=[protocol.todo_to_json(t) for t in todos]
        )

    async def add_diff_box(
        self,
        old_content: str,
        new_content: str,
        title: str | None = None,
    ) -> DiffBox:
        handle = await self._create_box(
            "add_diff_box", title=title, old=old_content, new=new_content
        )
        return _WireDiffBox(self, handle)

    async def add_tree_box(
        self,
        metadata: FileMetadata,
        title: str | None = None,
        display_metadata: bool = False,
    ) -> TreeBox:
        handle = await self._create_box(
            "add_tree_box",
            title=title,
            metadata=protocol.metadata_to_json(metadata),
        )
        return _WireTreeBox(self, handle)

    async def add_text_box(
        self,
        text: str,
        title: str | None = None,
        language: str | None = None,
        collapsed: bool = False,
    ) -> TextBox:
        handle = await self._create_box(
            "add_text_box",
            title=title,
            text=text,
            language=language,
            collapsed=collapsed,
        )
        return _WireTextBox(self, handle)

    def add_stat(
        self,
        label: str,
        get: Callable[[], Any],
        on_click: Callable[[], Awaitable[None]] | None = None,
        render: Callable[[Any], str] | None = None,
    ) -> Stat:
        # A Stat's value is computed server-side; the wire carries label + text.
        value = get()
        self._publish(
            {
                "type": "stat",
                "label": label,
                "text": render(value) if render else str(value),
            }
        )
        return _WireStat(self)

    @asynccontextmanager
    async def with_group(
        self, title: str, auto_collapse: bool = False
    ) -> AsyncGenerator[SolveigInterface, Any]:
        gid = self._next_id()
        # `parent` is the group THIS interface represents — None for the root,
        # the group id for a `_WireGroup`. It is WHO CALLED with_group, not a
        # stack peek, so a group created on another group pins that one as its
        # parent even when frames interleave with siblings.
        parent: int | None = self._group_id
        self._publish(
            {"type": "group_start", "id": gid, "title": title, "parent": parent}
        )
        await self._flush()
        try:
            # Yield a SCOPED child that pins its own id on every frame it emits,
            # rather than `self` — the caller's explicit reference IS the target,
            # so two parallel open groups draw into their own group, never "the
            # latest one".
            yield _WireGroup(self, gid)
        finally:
            self._publish({"type": "group_end", "id": gid})
            await self._flush()

    async def set_status(
        self, status: str | None, duration: float | None = None
    ) -> None:
        await self._send_verb("set_status", status=status, duration=duration)

    def refresh_stats(self) -> None:
        self._publish({"type": "refresh_stats"})

    # -- lifecycle -----------------------------------------------------------

    @asynccontextmanager
    async def _animate(
        self,
        status: str = "Processing",
        final_status: str | None = None,
        timeout: float | None = None,
    ) -> AsyncGenerator[None]:
        await self.set_status(status)
        try:
            yield
        finally:
            await self.set_status(final_status)

    # -- input ---------------------------------------------------------------

    async def _ask_question(self, question: str, default: str = "") -> str:
        ask_id = self._next_id()
        future = asyncio.get_running_loop().create_future()
        self._asks[ask_id] = future
        self._publish(
            {
                "type": "ask",
                "id": ask_id,
                "kind": "question",
                "question": question,
                "default": default,
            }
        )
        await self._flush()
        try:
            return await future
        finally:
            self._asks.pop(ask_id, None)

    async def _ask_choice(self, question: str, choices: list[str]) -> int:
        ask_id = self._next_id()
        future = asyncio.get_running_loop().create_future()
        self._asks[ask_id] = future
        self._publish(
            {
                "type": "ask",
                "id": ask_id,
                "kind": "choice",
                "question": question,
                "choices": choices,
            }
        )
        await self._flush()
        try:
            answer = await future
            return int(answer) if answer.isdigit() else choices.index(answer)
        finally:
            self._asks.pop(ask_id, None)


class _WireStat(Stat):
    """A Stat whose refresh re-broadcasts its value over the wire."""

    def __init__(self, server: WireInterface) -> None:
        super().__init__("", lambda: None)
        self._server = server

    def refresh(self) -> None:
        self._server.refresh_stats()


class _WireGroup(WireInterface):
    """The child `with_group` yields — every frame it emits is pinned to one id.

    It is NOT a second server: it shares the root's socket, id counter and all
    registries, and only shadows `_publish` so the tag on every frame is fixed
    to this group's id. That is the whole point — a caller holding `g` from
    `with_group(...)` can write to it even while a SIBLING group is also open,
    and each lands in its own group, never "the latest one". A fresh state per
    group here would be a bug: a message added inside the group would register
    its action closure in a dict the root's `_resolve_action` never consults.
    """

    def __init__(self, root: WireInterface, group_id: int) -> None:
        # Share the root's transport and registries; DO NOT run WireInterface's
        # own __init__, which would mint a fresh server, id counter and action/
        # ask maps — the very isolation a group must not have.
        object.__setattr__(self, "user_message_queue", root.user_message_queue)
        self._root = root
        #: This group's own id — what a `with_group` called HERE nests inside.
        self._group_id = group_id
        self._server = root._server
        self._writers = root._writers
        self._ids = root._widget_id
        self._message_actions = root._message_actions
        self._asks = root._asks
        self._boxes = root._boxes

    def _publish(self, frame: dict[str, Any]) -> None:
        # The group is forced, not read off a shared stack: a nested or sibling
        # caller holds THIS object, so ITS id is the one that travels.
        self._root._publish({**frame, "group": self._group_id})

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

    async def wait_until_ready(self) -> None:
        await self._root.wait_until_ready()
