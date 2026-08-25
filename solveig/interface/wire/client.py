"""WireClient — the adapter that makes a real interface speak the wire.

The daemon side (`WireInterface`) encodes ABC verbs to frames and broadcasts
them. This is THE OTHER END: it connects to the daemon socket, reads frames and
calls the matching method on a concrete `SolveigInterface`. So connecting a UI
to a daemon is "construct a WireClient over that UI" — the interchangeable half
the design log wants (broadcast interface for a daemon, TUI for a bare agent,
same protocol, same ABC seam).

Boxes cross as ids: when the daemon asks for a box under a handle id, this client
calls the interface's add verb, stores the returned real box under that id, and
routes later `invoke` frames to it. Message actions cross as NAMES, so this
client rebuilds a `MessageActions` whose closures forward an `action` frame back
to the daemon. The retraction (`ask_resolved`) cancels the local pending ask so
the other interface's winning answer is shown instead.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import AbstractAsyncContextManager
from typing import Any

from solveig.interface.base import MessageActions, Role, SolveigInterface
from solveig.interface.wire import protocol

#: ABC verb name -> the method the concrete interface must implement.
_METHODS = {
    "print": "print",
    "add_reasoning": "add_reasoning",
    "display_file_metadata": "display_file_metadata",
    "display_todos": "display_todos",
    "add_diff_box": "add_diff_box",
    "add_tree_box": "add_tree_box",
    "add_text_box": "add_text_box",
    "set_status": "set_status",
}

#: Verb -> a translator that turns the raw frame `args` into the args the
#: concrete method wants (domain objects come back from their JSON form; the
#: wire carries the `Level` NAME, the interface wants the enum).
_TRANSLATE = {
    "print": lambda a: {
        **a,
        "level": protocol.level_from_name(a["level"]),
    },
    "add_tree_box": lambda a: {
        **a,
        "metadata": protocol.metadata_from_json(a["metadata"]),
    },
    "display_todos": lambda a: {
        "todos": [protocol.todo_from_json(t) for t in a["todos"]],
    },
}


class WireClient:
    """Connects a concrete `SolveigInterface` to a daemon's wire socket."""

    def __init__(self, interface: SolveigInterface) -> None:
        self.interface = interface
        # self._socket_path = socket_path
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        #: Server handle id -> the real box the interface handed back.
        self._boxes: dict[int, Any] = {}
        #: Pending ask id -> the interface's in-flight ask (for retraction).
        self._asks: dict[int, asyncio.Task[Any]] = {}
        #: Open group id -> the scoped interface the real `with_group` yielded.
        #: Verbs tagged with a group id route here; the ROOT (no group) routes
        #: to `self.interface`. Keyed by id, not stacked, so two parallel open
        #: groups each keep their own target — exactly like the server side.
        self._groups: dict[int, _GroupScope] = {}
        self._ready = asyncio.Event()

    # -- transport -----------------------------------------------------------

    async def start(self) -> None:
        self._reader, self._writer = await asyncio.open_unix_connection(
            self.interface.config.interface.broadcast.socket
        )
        try:
            while line := await self._reader.readline():
                if not line:
                    break
                frame = json.loads(line)
                if frame.get("type") == "ready":
                    # The server replayed retained history then a `ready` marker:
                    # everything before this frame is caught up, everything after
                    # is live. Promoted now — wait_until_ready resolves from here.
                    self._ready.set()
                    continue
                await self._dispatch(frame)
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

    def _send(self, frame: dict[str, Any]) -> None:
        if self._writer is not None:
            self._writer.write(json.dumps(frame).encode() + b"\n")

    async def _flush(self) -> None:
        if self._writer is not None:
            await self._writer.drain()

    # -- dispatch -------------------------------------------------------------

    async def _dispatch(self, frame: dict[str, Any]) -> None:
        ftype = frame.get("type")
        if ftype == "verb":
            await self._on_verb(frame)
        elif ftype == "invoke":
            await self._on_invoke(frame)
        elif ftype == "ask":
            await self._on_ask(frame)
        elif ftype == "ask_resolved":
            self._cancel_ask(frame.get("id"))
        elif ftype == "group_start":
            await self._on_group_start(frame)
        elif ftype == "group_end":
            await self._on_group_end(frame)
        elif ftype == "refresh_stats":
            self.interface.refresh_stats()
        elif ftype == "config_update":
            await self._on_config_update(frame)
        # Unknown types are IGNORED — the forward-compat law of the format.

    def _target(self, frame: dict[str, Any]) -> SolveigInterface:
        """The interface a frame draws into: its group's scope, or the root."""
        gid = frame.get("group")
        if gid is not None:
            scope = self._groups.get(gid)
            if scope is not None:
                return scope.interface
        return self.interface

    async def _on_group_start(self, frame: dict[str, Any]) -> None:
        gid, title = int(frame["id"]), frame["title"]
        # Enter the REAL interface's group scope. The parent is the group whose
        # scope we're inside (None => root); we open on the parent's interface.
        parent = frame.get("parent")
        owner = self._groups[parent].interface if parent is not None else self.interface
        scope = _GroupScope(owner, title)
        await scope.enter()
        self._groups[gid] = scope

    async def _on_group_end(self, frame: dict[str, Any]) -> None:
        scope = self._groups.pop(int(frame["id"]), None)
        if scope is not None:
            await scope.close()

    async def _on_verb(self, frame: dict[str, Any]) -> None:
        verb = frame["verb"]
        handle_id = frame.get("id")
        target = self._target(frame)

        if verb == "add_message":
            # Actions cross as NAMES: rebuild MessageActions whose closures send
            # an `action` frame back to the daemon (which holds the real ones).
            args = frame.get("args") or {}
            box = await target.add_message(
                args.get("text", ""),
                Role(args.get("role", "user")),
                self._rebuild_actions(handle_id, args.get("actions", [])),
            )
            if handle_id is not None and box is not None:
                self._boxes[handle_id] = box
            return

        method = _METHODS.get(verb)
        if method is None:
            return
        args = dict(frame.get("args") or {})
        translate = _TRANSLATE.get(verb)
        if translate is not None:
            args = translate(args)
        box = await getattr(target, method)(**args)
        if handle_id is not None and box is not None:
            self._boxes[handle_id] = box

    def _rebuild_actions(
        self, message_id: int | None, action_names: list[str]
    ) -> MessageActions:
        """Rebuild a MessageActions whose closures forward over the wire.

        The daemon holds the REAL closures; this client only carries the names
        it offered, so invoking one is "send the daemon an action frame". The
        daemon resolves it against the real closure. Only the buttons the
        daemon said exist are offered.
        """
        offered = set(action_names)

        async def _edit(text: str) -> None:
            self._send(
                {
                    "type": "action",
                    "message_id": message_id,
                    "action": "edit",
                    "text": text,
                }
            )
            await self._flush()

        async def _fire(name: str) -> None:
            self._send({"type": "action", "message_id": message_id, "action": name})
            await self._flush()

        return MessageActions(
            edit=_edit if "edit" in offered else None,
            retry=(lambda: _fire("retry")) if "retry" in offered else None,
            delete=(lambda: _fire("delete")) if "delete" in offered else None,
            branch=(lambda: _fire("branch")) if "branch" in offered else None,
        )

    async def _on_invoke(self, frame: dict[str, Any]) -> None:
        box = self._boxes.get(int(frame.get("id", 0)))
        if box is None:
            return
        args = dict(frame.get("args") or {})
        # A tree's replace carries metadata, reconstructed before the call.
        if frame.get("method") == "replace" and "metadata" in args:
            args["metadata"] = protocol.metadata_from_json(args["metadata"])
        method = getattr(box, frame["method"], None)
        if method is not None:
            await method(**args)

    async def _on_ask(self, frame: dict[str, Any]) -> None:
        ask_id = int(frame.get("id", 0))
        task: asyncio.Task[Any]
        if frame.get("kind") == "choice":
            task = asyncio.ensure_future(
                self.interface.ask_choice(frame["question"], frame.get("choices", []))
            )
        else:
            task = asyncio.ensure_future(
                self.interface.ask_question(frame["question"], frame.get("default", ""))
            )
        self._asks[ask_id] = task
        try:
            value = await task
        except asyncio.CancelledError:
            return  # a concurrent answer elsewhere resolved this ask
        self._send(
            {
                "type": "answer",
                "id": ask_id,
                "value": str(value),
            }
        )
        await self._flush()

    def _cancel_ask(self, ask_id: int | None) -> None:
        if ask_id is None:
            return
        task = self._asks.pop(ask_id, None)
        if task is not None:
            task.cancel()

    async def _on_config_update(self, frame: dict[str, Any]) -> None:
        """Change the interface's own config based on the received update."""
        for path, value in frame.get("updates", {}).items():
            await self.interface.config.set(path, value)


class _GroupScope:
    """One open group on the client: the real interface's with_group entered.

    `with_group` is an async context manager, but its lifetime on the wire spans
    many frames (everything tagged with the group id until group_end). So the
    client drives it manually: enter it on `group_start` to get the scoped
    child, keep it open across verb frames, exit it on `group_end`.
    """

    def __init__(self, owner: SolveigInterface, title: str) -> None:
        self._owner = owner
        self._title = title
        self._cm: AbstractAsyncContextManager[SolveigInterface] | None = None
        #: The scoped child the real interface yielded; set on enter().
        self.interface: SolveigInterface = owner

    async def enter(self) -> None:
        cm = self._owner.with_group(self._title)
        self.interface = await cm.__aenter__()
        self._cm = cm

    async def close(self) -> None:
        if self._cm is not None:
            await self._cm.__aexit__(None, None, None)
            self._cm = None
