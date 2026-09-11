"""
WireClient — the adapter that makes a real interface speak the wire language.

The daemon side (`WireInterface`) encodes ABC verbs to frames and broadcasts
them. This is other end; it connects to the daemon socket, reads frames and
calls the matching method on a concrete `SolveigInterface`, and sends back
user input, answers to questions/choices, and calls to message actions.
So connecting a UI to a daemon is means constructing a WireClient over that
UI and the design allows swapping between a single process or a daemon with
broadcast without the app knowing.

NOTE: Boxes cross as ids. When the daemon creates a box under a handle id, this
client calls the interface's add verb, stores the returned real box under that id,
and routes later mutation frames to it. Message actions cross as names, so this
client rebuilds a `MessageActions` whose closures forward an `Action` frame back
to the daemon.

NOTE: Pending questions are resolved through an `AskResolved` frame. The first UI
to respond is declared winner by the daemon, who broadcasts the question_id+answer.
Any interfaces with the question pending must cancel it and should show the answer.

TODO: Confirm pending questions are cancelled by ID.
"""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from typing import Any

from pydantic import ValidationError

from solveig.interface.base import MessageActions, SolveigInterface
from solveig.interface.wire import protocol


class WireClient:
    """Connects a concrete `SolveigInterface` to a daemon's wire socket."""

    def __init__(self, interface: SolveigInterface) -> None:
        self.interface = interface
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        #: Server handle id -> the real box the interface handed back.
        self._boxes: dict[int, Any] = {}
        #: Pending ask id -> the interface's in-flight ask (for retraction).
        self._asks: dict[int, asyncio.Task[Any]] = {}
        #: Open group id -> the scoped interface the real `with_group` yielded.
        #: Verbs tagged with a group id route here; an untagged frame routes to
        #: `self.interface`. Keyed by id, not stacked, so two parallel open
        #: groups each keep their own target — exactly like the daemon side.
        self._groups: dict[int, _GroupScope] = {}
        #: Stat label -> the daemon's latest value for it and the handle showing
        #: it, as ONE entry: the text and the Stat are one fact about one label,
        #: and two maps keyed the same way would be a pair to keep in step.
        self._stats: dict[str, _PushedStat] = {}
        self._ready = asyncio.Event()

        # The queue's gate, so typed input leaves as a frame instead of landing
        # in a local queue no agent loop is reading. Returning None swallows it
        # here; the daemon's queue is the only real one.
        interface.user_message_queue.on_prompt(self._forward_input)

    # -- transport -----------------------------------------------------------

    async def start(self) -> None:
        self._reader, self._writer = await asyncio.open_unix_connection(
            self.interface.config.interface.broadcast.socket
        )
        try:
            while line := await self._reader.readline():
                try:
                    frame = protocol.SERVER_FRAMES.validate_json(line)
                except ValidationError:
                    # A kind this client does not know, or a malformed line:
                    # skip it and keep reading. THE forward-compat law of the
                    # format, and now the only thing it covers - a frame this
                    # client should have handled fails at the match instead of
                    # disappearing in here.
                    continue
                try:
                    await self._dispatch(frame)
                except Exception:
                    # One bad frame must not end the connection. Without this,
                    # any error while drawing (a widget that refuses a value, a
                    # cancelled prompt) silently turns a live client into a dead
                    # one that is still holding a socket open.
                    continue
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            for task in list(self._asks.values()):
                task.cancel()
            self._asks.clear()
            for scope in list(self._groups.values()):
                await scope.close()
            self._groups.clear()

    async def wait_until_ready(self) -> None:
        await self._ready.wait()

    async def stop(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except ConnectionError:
                pass
            self._writer = None

    async def _send(self, frame: protocol.ClientFrame) -> None:
        if self._writer is None:
            return
        self._writer.write(frame.model_dump_json().encode() + b"\n")
        await self._writer.drain()

    # -- inbound -------------------------------------------------------------

    async def _dispatch(self, frame: protocol.ServerFrameType) -> None:
        """One frame in, one interface call out.

        A `match` over frame CLASSES, so a frame kind added to the union with
        no arm here is a type error rather than a value silently falling
        through - which is exactly how `stat` went unrendered for as long as it
        did under the old string dispatch.
        """
        target = self._target(frame)
        match frame:
            # -- lifecycle
            case protocol.Ready():
                # Retained history has been replayed; everything after this is
                # live. `wait_until_ready` resolves from here.
                self._ready.set()

            # -- groups
            case protocol.GroupStart():
                await self._on_group_start(frame)
            case protocol.GroupEnd():
                scope = self._groups.pop(frame.id, None)
                if scope is not None:
                    await scope.close()

            # -- display verbs
            case protocol.Print():
                await target.print(frame.text, frame.level, prefix=frame.prefix)
            case protocol.AddReasoning():
                self._boxes[frame.id] = await target.add_reasoning(frame.text)
            case protocol.DisplayFileMetadata():
                await target.display_file_metadata(frame.path, prefix=frame.prefix)
            case protocol.DisplayTodos():
                await target.display_todos(frame.todos)
            case protocol.AddDiffBox():
                self._boxes[frame.id] = await target.add_diff_box(
                    frame.old, frame.new, frame.title
                )
            case protocol.AddTreeBox():
                self._boxes[frame.id] = await target.add_tree_box(
                    frame.metadata, frame.title
                )
            case protocol.AddTextBox():
                self._boxes[frame.id] = await target.add_text_box(
                    frame.text, frame.title, frame.language, frame.collapsed
                )
            case protocol.AddMessage():
                self._boxes[frame.id] = await target.add_message(
                    frame.text,
                    frame.role,
                    self._rebuild_actions(frame.id, frame.actions),
                )
            case protocol.SetStatus():
                await target.set_status(frame.status, frame.duration)

            # -- box mutations
            case protocol.TextAppend():
                await self._on_box(frame.id, "append", text=frame.text)
            case protocol.TextClear():
                await self._on_box(frame.id, "clear")
            case protocol.TextReplace() | protocol.MessageReplace():
                await self._on_box(frame.id, "replace", text=frame.text)
            case protocol.DiffReplace():
                await self._on_box(
                    frame.id, "replace", old_content=frame.old, new_content=frame.new
                )
            case protocol.TreeReplace():
                await self._on_box(frame.id, "replace", metadata=frame.metadata)
            case protocol.TreeRefresh():
                await self._on_box(frame.id, "refresh")
            case protocol.MessageRemove():
                await self._on_box(frame.id, "remove")

            # -- consent
            case protocol.AskQuestion() | protocol.AskChoice():
                await self._on_ask(frame, target)
            case protocol.AskResolved():
                task = self._asks.pop(frame.id, None)
                if task is not None:
                    task.cancel()

            # -- stats and config
            case protocol.StatValue():
                self._on_stat(frame)
            case protocol.RefreshStats():
                self.interface.refresh_stats()
            case protocol.ConfigUpdate():
                # TODO: how to fix this one without config.set()?
                for path, value in frame.updates.items():
                    await self.interface.config.set(path, value)

    def _target(self, frame: protocol.ServerFrame) -> SolveigInterface:
        """The interface a frame draws into: its group's scope, or the root."""
        if frame.group is not None:
            scope = self._groups.get(frame.group)
            if scope is not None:
                return scope.interface
        return self.interface

    async def _on_box(self, box_id: int, method: str, **args: Any) -> None:
        box = self._boxes.get(box_id)
        if box is not None:
            await getattr(box, method)(**args)

    async def _on_group_start(self, frame: protocol.GroupStart) -> None:
        # Enter the REAL interface's group scope. `parent` is the group that
        # CONTAINS this one (None => root), so nesting is read from the frame
        # rather than guessed from arrival order.
        owner = (
            self._groups[frame.parent].interface
            if frame.parent is not None and frame.parent in self._groups
            else self.interface
        )
        scope = _GroupScope(owner, frame.title, frame.collapse_when_done)
        await scope.enter()
        self._groups[frame.id] = scope

    def _on_stat(self, frame: protocol.StatValue) -> None:
        """Register or update one stat the daemon pushed.

        First frame for a label registers it, every later one updates it.
        """
        existing = self._stats.get(frame.label)
        if existing is None:
            self._stats[frame.label] = _PushedStat(
                self.interface, frame.label, frame.text
            )
        else:
            existing.update(frame.text)

    async def _on_ask(
        self,
        frame: protocol.AskQuestion | protocol.AskChoice,
        target: SolveigInterface,
    ) -> None:
        """Raise the daemon's prompt locally and send back the answer.

        Calls the PRIVATE `_ask_*`: the daemon already ran the public verb, so
        whatever it appended (the "Cancel processing" choice) is in the text
        that arrived. Going through the public one here would append it a
        second time, and choosing it would raise `UserCancel` in a coroutine
        whose only job is to answer a socket.
        """
        coro = (
            target._ask_choice(frame.question, frame.choices)
            if isinstance(frame, protocol.AskChoice)
            else target._ask_question(frame.question, frame.default)
        )
        task: asyncio.Task[Any] = asyncio.ensure_future(coro)
        self._asks[frame.id] = task
        try:
            value = await task
        except asyncio.CancelledError:
            return  # a concurrent answer elsewhere resolved this ask
        finally:
            # Popped on EVERY exit, not just cancellation - an answered ask
            # that stayed in the map would be cancelled again at disconnect.
            self._asks.pop(frame.id, None)
        await self._send(protocol.Answer(id=frame.id, value=str(value)))

    def _rebuild_actions(
        self, message_id: int, action_names: list[protocol.ActionName]
    ) -> MessageActions:
        """Rebuild a MessageActions whose closures forward over the wire.

        The daemon holds the REAL closures; this client only carries the names
        it offered, so invoking one is "send the daemon an Action frame". The
        daemon resolves it against the real closure. Only the buttons the
        daemon said exist are offered.
        """
        offered = set(action_names)

        async def _edit(text: str) -> None:
            await self._send(
                protocol.Action(
                    message_id=message_id,
                    action=protocol.ActionName.EDIT,
                    text=text,
                )
            )

        def _fire(name: protocol.ActionName):
            async def _send() -> None:
                await self._send(protocol.Action(message_id=message_id, action=name))

            return _send

        return MessageActions(
            edit=_edit if protocol.ActionName.EDIT in offered else None,
            retry=(
                _fire(protocol.ActionName.RETRY)
                if protocol.ActionName.RETRY in offered
                else None
            ),
            delete=(
                _fire(protocol.ActionName.DELETE)
                if protocol.ActionName.DELETE in offered
                else None
            ),
            branch=(
                _fire(protocol.ActionName.BRANCH)
                if protocol.ActionName.BRANCH in offered
                else None
            ),
        )

    # -- outbound ------------------------------------------------------------

    async def _forward_input(self, text: str) -> str | None:
        """The queue's prompt gate: send the text on, enqueue nothing here.

        Returning `None` swallows the local insert, which is the point - the
        agent loop draining a queue lives in the daemon, and a message parked
        in this client's queue would never be read by anything.
        """
        await self._send(protocol.Input(text=text))
        return None

    async def cancel(self, group: int | None = None) -> None:
        """Ask the daemon to stop work. `None` means everything it is doing.

        A request, not a cancellation: every cancel scope lives in the daemon
        because that is where the agent loop, the tools and the model requests
        run. Nothing here can stop work in another process.
        """
        await self._send(protocol.Cancel(group=group))


class _PushedStat:
    """One stat the daemon pushes, and the local Stat that shows it.

    A `Stat` holds no value: `read` PULLS from a live source. Here there is no
    such source - the value exists only as whatever arrived last - so this
    object IS it, and `read` pulls from the text on this object. That keeps the
    contract intact rather than teaching every frontend to store values for the
    sake of the one that has to.

    Constructed with its text already set, so `add_stat` can be called from
    here and there is no moment where the handle exists without a value to
    read.
    """

    def __init__(self, interface: SolveigInterface, label: str, text: str) -> None:
        self.text = text
        self.handle = interface.add_stat(label, lambda: self.text)

    def update(self, text: str) -> None:
        self.text = text
        self.handle.refresh()


class _GroupScope:
    """One open group on the client: the real interface's with_group entered.

    `with_group` is an async context manager, but its lifetime on the wire spans
    many frames (everything tagged with the group id until GroupEnd). So the
    client drives it manually: enter it on `GroupStart` to get the scoped
    child, keep it open across frames, exit it on `GroupEnd`.
    """

    def __init__(
        self, owner: SolveigInterface, title: str, collapse_when_done: bool = True
    ) -> None:
        self._owner = owner
        self._title = title
        self._collapse_when_done = collapse_when_done
        self._cm: AbstractAsyncContextManager[SolveigInterface] | None = None
        #: The scoped child the real interface yielded; set on enter().
        self.interface: SolveigInterface = owner

    async def enter(self) -> None:
        cm = self._owner.with_group(self._title, self._collapse_when_done)
        self.interface = await cm.__aenter__()
        self._cm = cm

    async def close(self) -> None:
        if self._cm is not None:
            await self._cm.__aexit__(None, None, None)
            self._cm = None
