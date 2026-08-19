"""An asyncio fan-out of display events to connected web clients.

`EventStream` is the web frontend's answer to the reactive seam every other
frontend shares: where `SessionDisplay` calls interface verbs and a Terminal
widget mounts, here the `WebInterface` serializes each verb to a JSON event and
this bus pushes it to every open SSE connection.

Two responsibilities, kept deliberately:

- `publish` fans out one event to all current subscribers (an `asyncio.Queue`
  per connection; single-flight, so ordering is preserved per client).
- a retained `_history` of every event ever published, so a browser that
  connects late (a refresh, a second tab, a reconnect after the SSE stream
  dropped) is replayed the same events a client present from the start saw.
  That is the "replay is not a special path" rule applied to the wire: a
  client is just a subscriber that started at event 0, regardless of when it
  actually subscribed.

Events are plain JSON-serializable dicts carrying a `type` discriminator; the
frontend renders one type. Nothing about pydantic-ai or a message id crosses
this bus - exactly like the interface verbs, what travels is what a screen
needs to draw.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any


class EventStream:
    """Fan-out of JSON-serializable display events to SSE subscribers.

    Holds no reference to the interface or the conversation - neither is its
    business. Producers call `publish` with an already-serialized event;
    consumers `subscribe()` to get an outbox drained of history-then-live.
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._history: list[dict[str, Any]] = []

    def publish(self, event: dict[str, Any]) -> None:
        """Broadcast one event to every connected client and retain it.

        Duplicates are the caller's concern, not ours: if the same event lands
        here twice, every client renders it twice. Producers emit once per
        logical change.
        """
        self._history.append(event)
        payload = json.dumps(event)
        for queue in list(self._subscribers):
            queue.put_nowait(payload)

    def subscribe(self) -> asyncio.Queue[str]:
        """A new client outbox, seeded with history then live events.

        Registered before seeding so no event can slip between the two. The
        consumer feeds its SSE stream from this queue and must call `discard`
        when the connection ends.
        """
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._subscribers.add(queue)
        for event in self._history:
            queue.put_nowait(json.dumps(event))
        return queue

    def discard(self, queue: asyncio.Queue[str]) -> None:
        """Drop a client outbox (that connection went away)."""
        self._subscribers.discard(queue)
