"""Wire: the wire protocol connects remote interfaces to one daemon broadcast.

These tests spin up a real `WireInterface` (the daemon's server socket), attach
two `WireClient`s each driving a `MockInterface`, and verify the ABC verbs cross
as frames end-to-end: verb broadcast to all clients, box handles as invoke
frames, asks broadcast with first-answer-wins + retraction, and message actions
forwarded back to the daemon's real closures.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest

from solveig.interface.base import MessageActions, Role
from solveig.interface.wire import WireClient, WireInterface
from tests.mocks.interface import MockInterface


@asynccontextmanager
async def _serve(
    server: WireInterface,
) -> AsyncGenerator[asyncio.Task]:
    """Run the server's accept loop in the background, stop on exit."""
    task = asyncio.create_task(server.start())
    await server.wait_until_ready()
    try:
        yield task
    finally:
        await server.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _clients(path: pathlib.Path, *interfaces: MockInterface) -> list[WireClient]:
    clients = [WireClient(interface=itf, socket_path=str(path)) for itf in interfaces]
    # start() runs the read loop; it must be a background task, not awaited.
    # The tasks are left fire-and-forget — the client keeps itself alive and
    # tests stop the clients explicitly.
    for c in clients:
        asyncio.create_task(c.start())
    await asyncio.gather(*(c.wait_until_ready() for c in clients))
    return clients


def test_protocol_roundtrips() -> None:
    """Serialization helpers survive their own round trip."""
    from solveig.interface.wire import protocol
    from solveig.todo import TodoItem
    from solveig.utils.file import FileMetadata

    child = FileMetadata(
        owner_name="o",
        group_name="g",
        path="/a/b/c",
        size=1,
        is_directory=False,
        is_readable=True,
        is_writable=True,
        modified_time=1,
    )
    md = FileMetadata(
        owner_name="o",
        group_name="g",
        path="/a/b",
        size=4,
        is_directory=True,
        is_readable=True,
        is_writable=True,
        modified_time=1,
        listing={"c": child},
        line_count=None,
    )
    rebuilt = protocol.metadata_from_json(protocol.metadata_to_json(md))
    assert rebuilt.path == md.path
    assert rebuilt.listing["c"].path == "/a/b/c"

    item = TodoItem(content="x", status="in_progress")
    assert protocol.todo_from_json(protocol.todo_to_json(item)).content == "x"
    assert (
        protocol.todo_from_json(protocol.todo_to_json(item)).status.value
        == "in_progress"
    )


@pytest.mark.anyio
async def test_broadcast_print_to_all_clients(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "solveig.sock"
    server = WireInterface(socket_path=str(path))
    async with _serve(server):
        [one, two] = await _clients(path, MockInterface(), MockInterface())
        await server.print("hello", prefix="P")
        await asyncio.sleep(0.2)
        # The mock renders a prefixed print as "[TEXT: P] hello".
        assert any("[TEXT: P] hello" in line for line in one.interface.outputs)
        assert any("[TEXT: P] hello" in line for line in two.interface.outputs)
        await asyncio.gather(one.stop(), two.stop())


@pytest.mark.anyio
async def test_add_text_box_then_invoke_reaches_clients(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "solveig.sock"
    server = WireInterface(socket_path=str(path))
    async with _serve(server):
        [one, two] = await _clients(path, MockInterface(), MockInterface())
        box = await server.add_text_box("apt output", title="Command")
        await box.append("Reading...")
        await asyncio.sleep(0.2)
        assert any("Reading..." in line for line in one.interface.outputs)
        assert any("Reading..." in line for line in two.interface.outputs)
        await asyncio.gather(one.stop(), two.stop())


@pytest.mark.anyio
async def test_ask_first_answer_wins(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "solveig.sock"
    server = WireInterface(socket_path=str(path))
    first = MockInterface()
    second = MockInterface()
    async with _serve(server):
        [one, two] = await _clients(path, first, second)
        # The daemon broadcasts the same ask to both clients; either may answer
        # first (a real race), and whichever wins resolves the server's wait.
        first.user_inputs[:] = ["A"]
        second.user_inputs[:] = ["B"]
        result = await server.ask_question("Which file?")
        assert result in ("A", "B")
        await asyncio.gather(one.stop(), two.stop())


@pytest.mark.anyio
async def test_add_message_action_forwards_to_daemon(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "solveig.sock"
    server = WireInterface(socket_path=str(path))
    called: list[str] = []

    async def edit(text: str) -> None:
        called.append(text)

    async with _serve(server):
        [one] = await _clients(path, MockInterface())
        await server.add_message("hello", Role.USER, MessageActions(edit=edit))
        await asyncio.sleep(0.2)
        # The client rebuilt the actions so the mock's offered edit closure sends
        # an `action` frame; the daemon resolves it against the REAL closure.
        msg = one.interface.shown[-1]
        assert "edit" in msg.offered
        assert msg.actions.edit is not None
        await msg.actions.edit("rewritten")
        await asyncio.sleep(0.2)
        assert called == ["rewritten"]
        await one.stop()


@pytest.mark.anyio
async def test_parallel_groups_route_by_their_own_id(
    tmp_path: pathlib.Path,
) -> None:
    """Two concurrently-open groups tag their frames with their OWN id.

    The server's `with_group` yields a scoped `_WireGroup` per group; writing to
    one while its SIBLING is also open must emit frames tagged with THAT group's
    id, not "the latest one". Proven at the wire: a raw reader captures the
    frames and each print frame's `group` is the group it was written via.
    """
    path = tmp_path / "solveig.sock"
    server = WireInterface(socket_path=str(path))
    frames: list[dict] = []

    async with _serve(server):
        # A raw socket reader decodes every frame the server broadcasts.
        reader, writer = await asyncio.open_unix_connection(str(path))

        async def _drain():
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=0.5)
                if not line:
                    return
                frames.append(json.loads(line))

        drain = asyncio.create_task(_drain())
        # Wait for the server's `ready` marker rather than racing its accept
        # handler: the server replays retained history then `ready` before that
        # reader is live, so it is guaranteed registered before we publish.
        # (This is the membership race the old sleep(0.2) papered over.)
        async def _await_ready() -> None:
            while not any(f.get("type") == "ready" for f in frames):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_await_ready(), timeout=5)
        # with_group is an async context manager: drive it via __aenter__ and
        # hold the scoped child, exactly as the client does per group.
        g = server.with_group("Build")
        t = server.with_group("Test")
        g_s = await g.__aenter__()
        t_s = await t.__aenter__()
        await g_s.print("compiling")
        await t_s.print("running tests")
        await g_s.print("linked")
        await t_s.print("all green")
        await t.__aexit__(None, None, None)
        await g.__aexit__(None, None, None)
        await asyncio.sleep(0.4)
        drain.cancel()

        # group_start/groups are tagged with their own id...
        starts = {f["id"] for f in frames if f.get("type") == "group_start"}
        assert len(starts) == 2
        # ...and each verb frame's `group` is the one its emitter pinned.
        prints = [f for f in frames if f.get("verb") == "print"]
        text_to_group = {f["args"]["text"]: f.get("group") for f in prints}
        assert (
            text_to_group["compiling"] == text_to_group["linked"]
        )  # same group (Build)
        assert text_to_group["running tests"] == text_to_group["all green"]  # Test
        assert text_to_group["compiling"] != text_to_group["running tests"]
        assert set(text_to_group.values()) == starts
        writer.close()
        await server.stop()


@pytest.mark.anyio
async def test_late_client_is_replayed_history_before_ready(
    tmp_path: pathlib.Path,
) -> None:
    """A client that connects AFTER frames were published is caught up.

    The membership race: `_on_connect` promotes a writer to the broadcast set
    only when the accept handler runs, so a broadcast in that window can drop
    wholesale. The fix replays retained history plus a `ready` marker to every
    newcomer BEFORE it goes live — so a client is guaranteed to see everything
    published before it registered, in order.
    """
    path = tmp_path / "solveig.sock"
    server = WireInterface(socket_path=str(path))
    async with _serve(server):
        # Frames published BEFORE any client connects.
        await server.print("early", prefix="E")
        await server.add_text_box("seed", title="Seed")

        # The late reader connects after those frames — it must still see them.
        reader, writer = await asyncio.open_unix_connection(str(path))
        frames: list[dict] = []

        async def _drain() -> None:
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=0.5)
                if not line:
                    return
                frames.append(json.loads(line))

        drain = asyncio.create_task(_drain())
        # Block until the `ready` marker: everything before it is the replayed
        # past, everything after is live — and this reader must NOT miss the
        # early frames.
        async def _await_ready() -> None:
            while not any(f.get("type") == "ready" for f in frames):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_await_ready(), timeout=5)

        # A live frame, published after this reader was promoted.
        await server.print("live")
        await asyncio.sleep(0.2)
        drain.cancel()

        texts = [f["args"]["text"] for f in frames if f.get("verb") == "print"]
        assert texts == ["early", "live"]  # caught up, then live, in order
        # The text box created before this client connected is present too.
        made_boxes = sum(
            1
            for f in frames
            if f.get("type") == "verb" and f.get("verb") == "add_text_box"
        )
        assert made_boxes == 1
        writer.close()
        await server.stop()
