"""WireInterface — the daemon's broadcast surface over a socket.

`WireInterface` IS the seam the daemon's agent code talks to, exactly as it
talks to a `TerminalInterface` today: one object implementing `SolveigInterface`.
The difference is that its "screen" is every connected client (a second TUI, a
web UI, a telegram bot) — each verb is serialized to a wire frame and broadcast
to all live connections; the box a verb hands back is a `RemoteBox` whose
mutations are the next frame.

The design keeps the wire vocabulary tool-agnostic: a frame names an ABC surface
(`AddTreeBox(FileMetadata)`), never a tool, so a client renders any stream
forever and needs no plugin config. Boxes cross as ids — the daemon mints a
global handle id, broadcasts the create frame under it, and the client keys its
own local widget by that id, so a later mutation frame reaches every client.

Consent (`ask_*`) broadcasts to ALL clients, first answer wins; on resolve the
daemon broadcasts an `AskResolved` so every client cancels its pending prompt
and shows the winner's answer — the retraction the design log demands.

Every frame is a model from `protocol.py`, and inbound lines are validated
against the CLIENT union only: this end cannot receive a frame it is supposed to
send. A line whose kind this daemon does not know is skipped, which is what lets
daemons and clients at different feature levels share one stream.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

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

    from solveig.pending.user_message_queue import UserMessageQueue


def _encode(frame: protocol.ServerFrame) -> bytes:
    """One frame as one JSONL line - the single place a frame becomes bytes."""
    return frame.model_dump_json().encode() + b"\n"


# --------------------------------------------------------------------------- #
# Remote box handles — one frame per mutation, addressed to the handle id.     #
# --------------------------------------------------------------------------- #


class _WireBox:
    """A box handle whose mutations are frames addressed to its id.

    NOTE: publishes without draining, which is deliberate parity with how a
    local box draws: `write()` already schedules the send, and `drain()` only
    applies backpressure. A streamed message appends once per token, and
    awaiting every client's buffer on each one would make the daemon's
    throughput the slowest reader's.
    """

    def __init__(self, server: WireInterface, handle_id: int) -> None:
        self._server = server
        self._id = handle_id

    def _invoke(self, frame: protocol.BoxFrame) -> None:
        self._server._publish(frame)


class _WireTextBox(TextBox, _WireBox):
    async def append(self, text: str) -> None:
        self._invoke(protocol.TextAppend(id=self._id, text=text))

    async def clear(self) -> None:
        self._invoke(protocol.TextClear(id=self._id))

    async def replace(self, text: str) -> None:
        self._invoke(protocol.TextReplace(id=self._id, text=text))


class _WireDiffBox(DiffBox, _WireBox):
    async def replace(self, old_content: str, new_content: str) -> None:
        self._invoke(
            protocol.DiffReplace(id=self._id, old=old_content, new=new_content)
        )


class _WireTreeBox(TreeBox, _WireBox):
    async def replace(self, metadata: FileMetadata) -> None:
        self._invoke(protocol.TreeReplace(id=self._id, metadata=metadata))

    async def refresh(self) -> None:
        self._invoke(protocol.TreeRefresh(id=self._id))


class _WireMessageBox(MessageBox, _WireBox):
    async def replace(self, text: str) -> None:
        self._invoke(protocol.MessageReplace(id=self._id, text=text))

    async def remove(self) -> None:
        self._invoke(protocol.MessageRemove(id=self._id))


# --------------------------------------------------------------------------- #
# WireInterface                                                               #
# --------------------------------------------------------------------------- #


@dataclass
class _WireState:
    """
    The transport a root owns and every group under it reads.

    ONE object rather than six fields, because a group reaches all of it the
    same way (`self.root._state`) and there is nothing to copy or keep in step.
    `default_factory` throughout: as bare class attributes these would be
    SHARED by every root ever built, so two daemons in one process would write
    to the same socket set and mint colliding ids.
    """

    # Connected clients. A frame is written to each; a closed one is dropped.
    writers: set[asyncio.StreamWriter] = field(default_factory=set)
    # Every frame published to connected clients, in order.
    # Clients that connect later can replay a live stream from `history`
    history: list[protocol.ServerFrame] = field(default_factory=list)
    # Single counter for all transmitted widgets
    ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))
    # Message id -> action message Callables
    message_actions: dict[int, MessageActions] = field(default_factory=dict)
    # Ask id -> the future `ask_*` is waiting on. First answer in wins.
    asks: dict[int, asyncio.Future[str]] = field(default_factory=dict)
    # Group id -> the scoped interface, for the whole lifetime of that group.
    # An inbound frame names a group by id (only `Cancel` does today), and this
    # is what turns that id back into the object whose work it addresses.
    groups: dict[int, WireInterface] = field(default_factory=dict)
    # The stats registered on this root, in registration order. Held because a
    # Stat pulls its value on demand and the wire has to push: a refresh
    # re-reads every `read` and re-broadcasts, since no client can call one.
    stats: list[_WireStat] = field(default_factory=list)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    server: asyncio.AbstractServer | None = None


class WireInterface(SolveigInterface):
    """A SolveigInterface whose screen is every connected client socket.

    Starts a server in `start()` that awaits connections; every accepted client
    is added to the broadcast set. Verbs encode to frames and fan out; box
    handles and asks carry server-minted ids.
    """

    if TYPE_CHECKING:
        # The base can only promise the protocol; inside this frontend the root
        # is always a WireInterface, which is what makes `self.root._state`
        # typecheck. Declaration only - the runtime property is the base's.
        @property
        def root(self) -> WireInterface: ...

    #: The group this interface draws into; None on the root. Every frame it
    #: publishes carries it, so two parallel groups each tag their own.
    _group_id: int | None = None

    def __init__(
        self,
        config: SolveigConfig,
        user_message_queue: UserMessageQueue,
    ) -> None:
        super().__init__(config, user_message_queue)
        self._state = _WireState()

        # Root-only: observers cannot be unregistered, so a group registering
        # this too would multiply `config_update` frames per group ever opened.
        @self.config.on_change("interface")
        def on_config_update(_config: SolveigConfig, changed_paths: frozenset[str]):
            self._publish(
                protocol.ConfigUpdate(
                    updates={
                        # get the string representation of the field, not its object
                        path: _config.get(path, as_field=True)
                        for path in changed_paths
                    }
                )
            )

    # -- transport -----------------------------------------------------------

    async def start(self) -> None:
        """Bind the socket and serve clients until `stop()`."""
        state = self.root._state
        state.server = await asyncio.start_unix_server(
            self._on_connect, self.config.interface.broadcast.socket
        )
        state.ready.set()
        try:
            async with state.server:
                await state.server.serve_forever()
        finally:
            state.ready.clear()

    async def stop(self) -> None:
        # Close every connected client first so their handler loops end, THEN
        # the listening socket. Reversed, `wait_closed()` blocks forever on the
        # accepted connection's handler, which only returns when its client
        # goes away — and this daemon is the one deciding they all go now.
        state = self.root._state
        for writer in state.writers:
            writer.close()
        state.writers.clear()
        if state.server is not None:
            state.server.close()
            await state.server.wait_closed()
            state.server = None

    async def wait_until_ready(self) -> None:
        await self.root._state.ready.wait()

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
        state = self.root._state
        state.writers.add(writer)
        for frame in state.history:
            writer.write(_encode(frame))
        writer.write(_encode(protocol.Ready()))
        await writer.drain()
        try:
            while line := await reader.readline():
                try:
                    inbound = protocol.CLIENT_FRAMES.validate_json(line)
                except ValidationError:
                    # A kind this daemon does not know, or a malformed line.
                    # Skipping it is the forward-compat law; ending the
                    # connection over it would let a newer client disconnect
                    # itself just by greeting an older daemon.
                    continue
                await self._on_frame(inbound)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            state.writers.discard(writer)

    # -- fan-out -------------------------------------------------------------

    def _publish(self, frame: protocol.ServerFrame) -> None:
        """The one emission path, root and group alike.

        A group stamps every frame it publishes with its own id, and the root's
        is None so its frames carry none. The tag comes from the OBJECT doing
        the publishing, never from a stack, which is what lets two parallel
        groups each draw into their own instead of arguing over "the latest".
        """
        if self._group_id is not None:
            frame.group = self._group_id
        state = self.root._state
        state.history.append(frame)
        payload = _encode(frame)
        for writer in list(state.writers):
            try:
                writer.write(payload)
            except (ConnectionError, RuntimeError):
                continue

    async def _flush(self) -> None:
        for writer in list(self.root._state.writers):
            try:
                await writer.drain()
            except (ConnectionError, RuntimeError):
                pass

    async def _emit(self, frame: protocol.ServerFrame) -> None:
        """Publish and drain - the shape a verb uses when it has nothing else
        to do, so the frame is on its way before the caller moves on."""
        self._publish(frame)
        await self._flush()

    def _next_id(self) -> int:
        return next(self.root._state.ids)

    # -- inbound: answers, actions, input -------------------------------------

    async def _on_frame(self, frame: protocol.ClientFrameType) -> None:
        match frame:
            case protocol.Answer():
                future = self.root._state.asks.get(frame.id)
                if future is not None and not future.done():
                    future.set_result(frame.value)
                    # Retraction: broadcast the winner's answer so every other
                    # client cancels its pending prompt and shows it.
                    await self._emit(
                        protocol.AskResolved(id=frame.id, answer=frame.value)
                    )
            case protocol.Input():
                await self.user_message_queue.put(frame.text)
            case protocol.Action():
                await self._handle_message_action(frame)
            case protocol.Cancel():
                # Addressed by WHICH interface, exactly as a local cancel is:
                # `cancel_task()` reaches everything under the object it is
                # called on, so naming the group is the whole targeting.
                target = (
                    self.root._state.groups.get(frame.group, self.root)
                    if frame.group is not None
                    else self.root
                )
                target.cancel_task()

    async def _handle_message_action(self, frame: protocol.Action) -> None:
        actions = self.root._state.message_actions.get(frame.message_id)
        if actions is None:
            return
        match frame.action:
            case protocol.ActionName.EDIT if actions.edit is not None:
                await actions.edit(frame.text or "")
            case protocol.ActionName.RETRY if actions.retry is not None:
                await actions.retry()
            case protocol.ActionName.DELETE if actions.delete is not None:
                await actions.delete()
            case protocol.ActionName.BRANCH if actions.branch is not None:
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
        await self._emit(protocol.Print(text=text, level=level, prefix=prefix))

    async def add_message(
        self, text: str, role: Role, actions: MessageActions
    ) -> MessageBox:
        message_id = self._next_id()
        self.root._state.message_actions[message_id] = actions
        await self._emit(
            protocol.AddMessage(
                id=message_id,
                text=text,
                role=role,
                # Only the names, and only the ones actually offered - the real
                # closures stay here, and an `Action` frame comes back to them.
                actions=[
                    name
                    for name, fn in (
                        (protocol.ActionName.EDIT, actions.edit),
                        (protocol.ActionName.RETRY, actions.retry),
                        (protocol.ActionName.DELETE, actions.delete),
                        (protocol.ActionName.BRANCH, actions.branch),
                    )
                    if fn is not None
                ],
            )
        )
        return _WireMessageBox(self, message_id)

    async def add_reasoning(self, text: str) -> MessageBox:
        handle = self._next_id()
        await self._emit(protocol.AddReasoning(id=handle, text=text))
        return _WireMessageBox(self, handle)

    async def display_file_metadata(
        self,
        abs_path: str | PathLike,
        metadata: FileMetadata | None = None,
        prefix: str | None = None,
        is_directory: bool = False,
    ) -> None:
        await self._emit(
            protocol.DisplayFileMetadata(
                path=str(metadata.path if metadata is not None else abs_path),
                prefix=prefix,
            )
        )

    async def display_todos(self, todos: list[TodoItem]) -> None:
        await self._emit(protocol.DisplayTodos(todos=todos))

    async def add_diff_box(
        self,
        old_content: str,
        new_content: str,
        title: str | None = None,
    ) -> DiffBox:
        handle = self._next_id()
        await self._emit(
            protocol.AddDiffBox(
                id=handle, title=title, old=old_content, new=new_content
            )
        )
        return _WireDiffBox(self, handle)

    async def add_tree_box(
        self,
        metadata: FileMetadata,
        title: str | None = None,
        display_metadata: bool = False,
    ) -> TreeBox:
        handle = self._next_id()
        await self._emit(protocol.AddTreeBox(id=handle, title=title, metadata=metadata))
        return _WireTreeBox(self, handle)

    async def add_text_box(
        self,
        text: str,
        title: str | None = None,
        language: str | None = None,
        collapsed: bool = False,
    ) -> TextBox:
        handle = self._next_id()
        await self._emit(
            protocol.AddTextBox(
                id=handle,
                title=title,
                text=text,
                language=language,
                collapsed=collapsed,
            )
        )
        return _WireTextBox(self, handle)

    def _add_stat(
        self,
        label: str,
        read: Callable[[], Any],
        on_click: Callable[[], Awaitable[None]] | None = None,
        render: Callable[[Any], str] | None = None,
    ) -> Stat:
        # A Stat's value is computed daemon-side - it closes over a callable
        # that only exists here - so what crosses is the label and the text it
        # renders to right now. Held on the root so a refresh can re-read it:
        # nothing on a client can call `read`, so a push is the only way a stat
        # ever changes over the wire.
        stat = _WireStat(self.root, label, read, on_click, render)
        self.root._state.stats.append(stat)
        self._publish(stat.as_frame())
        return stat

    @asynccontextmanager
    async def with_group(
        self, title: str, collapse_when_done: bool = True
    ) -> AsyncGenerator[SolveigInterface, Any]:
        group = _WireGroup(self, title, collapse_when_done)
        async with group:
            # Membership for exactly the group's lifetime, which is what lets
            # `self.cancel_task()` reach work started inside it.
            self._children.add(group)
            try:
                yield group
            finally:
                self._children.discard(group)

    async def _set_status(
        self, status: str | None, duration: float | None = None
    ) -> None:
        await self._emit(protocol.SetStatus(status=status, duration=duration))

    def _refresh_stats(self) -> None:
        # Re-read every stat and push its current text. The bare marker frame
        # this used to send carried no values at all, so a client had nothing
        # to redraw WITH - the refresh has to be the values.
        for stat in self.root._state.stats:
            self._publish(stat.as_frame())
        self._publish(protocol.RefreshStats())

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

    def _open_ask(self) -> tuple[int, asyncio.Future[str]]:
        """Mint an ask id and the future the first answer resolves.

        The frame itself is built by the caller, because the two asks are two
        frame types now. Publishing it stamps THIS interface's group, which is
        how a client draws a consent prompt inside the tool that raised it -
        nothing identifying the group is passed anywhere, since the receiver IS
        the group.
        """
        ask_id = self._next_id()
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self.root._state.asks[ask_id] = future
        return ask_id, future

    async def _ask_question(self, question: str, default: str = "") -> str:
        ask_id, future = self._open_ask()
        await self._emit(
            protocol.AskQuestion(id=ask_id, question=question, default=default)
        )
        try:
            return await future
        finally:
            self.root._state.asks.pop(ask_id, None)

    async def _ask_choice(self, question: str, choices: list[str]) -> int:
        ask_id, future = self._open_ask()
        await self._emit(
            protocol.AskChoice(id=ask_id, question=question, choices=choices)
        )
        try:
            answer = await future
            return int(answer) if answer.isdigit() else choices.index(answer)
        finally:
            self.root._state.asks.pop(ask_id, None)


class _WireStat(Stat):
    """A Stat whose refresh re-broadcasts just its own value.

    It keeps the real `read`/`render` the owner registered, so `text` pulls from
    the live source exactly as a local stat does. `refresh()` addresses one
    entry - which is the point of `add_stat` handing the object back - rather
    than making every stat re-read because one of them changed.
    """

    def __init__(
        self,
        interface: WireInterface,
        label: str,
        read: Callable[[], Any],
        on_click: Callable[[], Awaitable[None]] | None = None,
        render: Callable[[Any], str] | None = None,
    ) -> None:
        super().__init__(label, read, on_click, render)
        self._interface = interface

    def as_frame(self) -> protocol.StatValue:
        return protocol.StatValue(label=self.label, text=self.text)

    def refresh(self) -> None:
        self._interface._publish(self.as_frame())


class _WireGroup(WireInterface):
    """One collapsible group on the wire: the same interface, tagging its id.

    It borrows nothing. The transport, the id counter and every registry are
    reached through `root`, so there is no field list to keep in step - the bug
    the previous hand-copying version shipped, having missed four of them. What
    it stores is only what it IS: who contains it, what it is called, and its
    own id.

    It announces itself, too: `group_start` on entry and `group_end` on exit,
    published THROUGH THE PARENT so the frame that opens a group carries the
    enclosing group's tag rather than its own.
    """

    def __init__(
        self, parent: WireInterface, title: str, collapse_when_done: bool = True
    ) -> None:
        # The BASE constructor, not WireInterface's - that one builds a fresh
        # transport and re-registers the config observer, which is exactly the
        # isolation a group must not have.
        SolveigInterface.__init__(self, parent.config, parent.user_message_queue)
        self._parent = parent
        self._title = title
        self._collapse_when_done = collapse_when_done
        self._group_id = self._next_id()

    async def __aenter__(self) -> _WireGroup:
        assert isinstance(self._parent, WireInterface)
        assert self._group_id is not None
        # Addressable for exactly its lifetime, so an inbound `Cancel` naming
        # this id reaches the object whose work it means.
        self.root._state.groups[self._group_id] = self
        # `parent` is WHO CONTAINS this group, so nesting survives frames
        # interleaving with siblings - it is never inferred from arrival order.
        # Published THROUGH the parent, so the frame that opens a group carries
        # the enclosing group's tag rather than its own.
        self._parent._publish(
            protocol.GroupStart(
                id=self._group_id,
                title=self._title,
                parent=self._parent._group_id,
                collapse_when_done=self._collapse_when_done,
            )
        )
        await self._flush()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        assert isinstance(self._parent, WireInterface)
        assert self._group_id is not None
        self.root._state.groups.pop(self._group_id, None)
        self._parent._publish(protocol.GroupEnd(id=self._group_id))
        await self._flush()
