"""The web group seam: a group is a scoped view of the root's screen.

`WebInterface.with_group` yields a `_WebGroup` that shares the root's bus, id
counter and action registry. That sharing is the whole point — a message drawn
inside a group must resolve its edit/retry/delete actions against the SAME
registry the HTTP layer reads (the root's), and it must never re-use an id the
root already handed out. Re-running the full initializer per group would mint a
fresh counter and a fresh `_message_actions` the root never consults, which is
exactly the isolation the wire `_WireGroup` seam comment names as a bug.
"""

from __future__ import annotations

import json

import pytest

from solveig.interface.base import MessageActions, Role
from solveig.interface.web import WebInterface


@pytest.mark.anyio
async def test_action_on_message_inside_group_resolves_at_root() -> None:
    """Actions registered in a group must answer through the root, because
    that is the object the HTTP layer calls `_resolve_action` on."""
    interface = WebInterface()
    fired: list[str] = []

    async def edit(text: str) -> None:
        fired.append(text)

    async with interface.with_group("Build") as group:
        box = await group.add_message(
            "summary", Role.ASSISTANT, MessageActions(edit=edit)
        )
        # The id came from the SHARED root counter, so the root knows the box.
        assert await interface._resolve_action(box._id, "edit", "rewritten")
        assert fired == ["rewritten"]


@pytest.mark.anyio
async def test_ids_do_not_collide_across_group_boundary() -> None:
    """The group mints ids from the root's counter, so no two objects — one
    inside a group, one outside — can ever share an id."""
    interface = WebInterface()
    outside = await interface.add_message(
        "first", Role.USER, MessageActions()
    )
    async with interface._scope("Inside") as gid:
        inside_box = await interface.add_message(
            "second", Role.USER, MessageActions()
        )
        # The group id and the message inside it are distinct from the root's.
        assert len({outside._id, gid, inside_box._id}) == 3
    assert outside._id != inside_box._id


@pytest.mark.anyio
async def test_group_shares_root_state_by_reference() -> None:
    """The `_WebGroup` must not re-run `WebInterface.__init__`, which would hand
    it a fresh counter and registry the root never sees."""
    interface = WebInterface()
    async with interface.with_group("Build") as group:
        # Same id counter object, same registries — not fresh copies.
        assert group._ids is interface._ids
        assert group._message_actions is interface._message_actions
        assert group._active_tasks is interface._active_tasks
        assert group.stream is interface.stream


@pytest.mark.anyio
async def test_group_start_carries_parent_id_links_nesting() -> None:
    """Nesting is declared by an explicit `parent` id, not by when a group was
    opened. A group opened inside another pins the outer group as its parent,
    so sibling groups can interleave without a stack."""
    from solveig.interface.web.bus import EventStream

    stream = EventStream()
    interface = WebInterface(stream=stream)
    # Every emit — root and groups alike — shares this one bus, so subscribe
    # sees all group_start frames in order.
    outbox = stream.subscribe()
    async with interface.with_group("Root") as root_group:
        async with root_group.with_group("Child") as child:
            async with root_group.with_group("Sibling") as sibling:
                pass
    # Drain whatever the outbox holds (history seed + live publishes).
    frames: list[dict] = []
    while not outbox.empty():
        frames.append(json.loads(outbox.get_nowait()))
    starts = [f for f in frames if f.get("type") == "group_start"]
    # Three groups, and each child's declared parent is the object it was
    # opened on — never the opening order.
    by_id = {s["id"]: s for s in starts}
    assert len(by_id) == 3
    assert by_id[root_group._gid]["parent"] is None
    assert by_id[child._gid]["parent"] == root_group._gid
    assert by_id[sibling._gid]["parent"] == root_group._gid
