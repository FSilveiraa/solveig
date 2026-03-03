"""Queue with peeking capabilities for user comments."""

import asyncio
from collections import deque
from collections.abc import Callable

from solveig.schema.message.user import UserComment


class PendingMessageQueue(asyncio.Queue):
    """Queue that allows non-destructive peeking of user comments.

    Extends asyncio.Queue to add:
    - get_user_comments(): Peek at UserComment items without consuming
    - set_on_change(): Register a callback fired on any put or get
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._queue: deque
        self._on_change: Callable[[], None] | None = None

    def set_on_change(self, callback: Callable[[], None]) -> None:
        self._on_change = callback

    def _notify(self) -> None:
        if self._on_change:
            self._on_change()

    async def put(self, item) -> None:
        await super().put(item)
        self._notify()

    def put_nowait(self, item) -> None:
        super().put_nowait(item)
        self._notify()

    async def get(self):
        item = await super().get()
        self._notify()
        return item

    def get_nowait(self):
        item = super().get_nowait()
        self._notify()
        return item

    def get_user_comments(self) -> list[UserComment]:
        """Get all user comments currently in the queue without consuming them."""
        return [item for item in self._queue if isinstance(item, UserComment)]

    def count_user_comments(self) -> int:
        """Count user comments in the queue."""
        return len(self.get_user_comments())
