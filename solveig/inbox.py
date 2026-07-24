"""The session's input inbox: user intent's single entry point.

An `asyncio.Queue` subclass (D5, project log 2026-07-24): every consumer uses
the stdlib Queue API unchanged (the main loop `await`s `get()`, the mid-turn
gate drains via `get_nowait()`, the interface's `on_user_input` is literally
`put_nowait`). It adds exactly two things:

- **A doorbell.** `_put`/`_get` are the internal hooks EVERY public mutator
  funnels through (verified in the CPython 3.13 asyncio source: `put`,
  `put_nowait`, `get`, `get_nowait` all bottom out in them), so the sync
  `on_change` callback fires on any mutation from any consumer. This is what
  lets `QueuedMessagesDisplay` react to the main loop draining the queue
  without any notify-by-courtesy plumbing (D0: reaction, not polling).
- **A read view.** `pending` exposes the queued items without consuming them
  (asyncio.Queue has no public peek), replacing the `queue._queue`
  private-attribute hack.
"""

import asyncio
from collections.abc import Callable


class Inbox(asyncio.Queue[str]):
    """asyncio.Queue + an `on_change` doorbell + a `pending` read view."""

    def __init__(self) -> None:
        super().__init__()
        # Sync callable (e.g. a Textual widget's update_display). Assigned by
        # whoever displays the inbox; fires after every put/get.
        self.on_change: Callable[[], None] | None = None

    def _put(self, item: str) -> None:
        super()._put(item)
        if self.on_change is not None:
            self.on_change()

    def _get(self) -> str:
        item = super()._get()
        if self.on_change is not None:
            self.on_change()
        return item

    @property
    def pending(self) -> tuple[str, ...]:
        """The queued items, oldest first, without consuming them."""
        # asyncio.Queue stores items in its private `_queue` deque and exposes
        # no public read; a subclass reading its own deque is the supported-
        # shape workaround (same class as the old `queue._queue` peek hack,
        # now confined to the one class that owns the queue).
        return tuple(self._queue)  # type: ignore[attr-defined]
