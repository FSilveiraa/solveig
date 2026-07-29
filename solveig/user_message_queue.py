"""The session's user-message queue: user intent's single entry point.

An `asyncio.Queue` subclass (D5, project log 2026-07-24): every consumer uses
the stdlib Queue API unchanged (the main loop `await`s `get()`, the mid-turn
gate drains via `get_nowait()`). It adds three things:

- **A prompt gate.** `put` runs the text through `prompt_handler` first: it
  returns the (possibly transformed) text to enqueue, or `None` to swallow
  the input (e.g. it was a /command, already executed). `put_nowait` is the
  ungated sync path for internal injection that bypasses routing.
- **A doorbell.** `_put`/`_get` are the internal hooks EVERY public mutator
  funnels through (verified in the CPython 3.13 asyncio source: `put`,
  `put_nowait`, `get`, `get_nowait` all bottom out in them), so the sync
  `on_change` callback fires on any mutation from any consumer. This is what
  lets `QueuedMessagesDisplay` react to the main loop draining the queue
  without any notify-by-courtesy plumbing (D0: reaction, not polling).
- **A read view.** `pending` exposes the queued items without consuming them
  (asyncio.Queue has no public peek), replacing the `queue._queue`
  private-attribute hack.

Named `UserMessageQueue` (not "Inbox"): a future Email-connection capability
will own that word; this class is exactly what it says - the queue of user
messages awaiting consumption.

KNOWN FLAW: the prompt handler runs the subcommand executor, which needs the
interface for display. A startup `/command` queued before the interface
attaches has no interface to render to. Tracked for a follow-up dispatcher
design.
"""

import asyncio
from collections.abc import Awaitable, Callable


class UserMessageQueue(asyncio.Queue[str]):
    """asyncio.Queue + a prompt gate + an `on_change` doorbell + a `pending` read view."""

    def __init__(self) -> None:
        super().__init__()
        # Async gate: text in -> text to enqueue, or None to swallow.
        # Wired post-construction by the composition root (needs the
        # subcommand executor; interface stays transitory at call time).
        self.prompt_handler: Callable[[str], Awaitable[str | None]] | None = None
        # Sync callable (e.g. a Textual widget's update_display). Assigned by
        # whoever displays the queue; fires after every put/get.
        self.on_change: Callable[[], None] | None = None

    async def put(self, text: str) -> None:
        """Gated insert: the prompt handler decides what actually lands in
        the queue (or swallows the input entirely)."""
        if self.prompt_handler is not None:
            gated = await self.prompt_handler(text)
            if gated is None:
                return
            text = gated
        await super().put(text)

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
