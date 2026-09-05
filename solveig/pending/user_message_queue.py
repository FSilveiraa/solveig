"""
The session's user-message queue: user intent's single entry point.

FIXME: a `/command` put on the queue before the interface has attached has
nowhere to render. The prompt filters for the registry runs the subcommand
executor, which needs the interface for display, and at that point there is none.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import override

from solveig.pending.user_message import PendingUserMessage


class UserMessageQueue(asyncio.Queue[PendingUserMessage]):
    """
    Follows asyncio.Queue API and holds pending user messages.
    Adds content inspection through `entries` and registering
    prompt filters and change observers.

    NOTE: `get_nowait` is not overriden and it's not supposed to call filters
    or observers. The reason is that `drain` uses `get_nowait` underneath
    and wants to call observers once per drain, not per message.
    """

    def __init__(self) -> None:
        super().__init__()
        # Filters to run on new user prompts
        self._prompt_filters: list[Callable[[str], Awaitable[str | None]]] = []
        # Observers to notify when the queue is altered
        self._on_change: list[Callable[[], None]] = []

    @property
    def entries(self) -> list[PendingUserMessage]:
        """Provides the queue items without consuming them, sorted by insertion order."""
        # HACK: asyncio.Queue stores items in a private `_queue` deque and
        # exposes no public read.
        return list(self._queue)  # type: ignore[attr-defined]

    # Decorators
    def on_change(self, call: Callable[[], None]) -> None:
        """Register a function to call when the queue changes (insertion or removal)."""
        self._on_change.append(call)

    def on_prompt(self, prompt_filter: Callable[[str], Awaitable[str | None]]) -> None:
        """
        Register a coroutine to filter the user prompt.
        The return value becomes the new prompt.
        If it returns None, the prompt isn't added to the queue
        """
        self._prompt_filters.append(prompt_filter)

    def _call_all_on_change(self) -> None:
        """Call all queue observers, notifying them it has been altered."""
        for call in self._on_change:
            call()

    # Main methods
    @override
    async def put(self, item: str | PendingUserMessage) -> None:
        """
        Runs prompt filters by registration order on the input before
        adding it to the queue, if any returns None the input isn't added.
        Otherwise, it's placed on the queue and observers are notified.
        """
        if isinstance(item, str):
            item = PendingUserMessage(item)
        for prompt_filter in self._prompt_filters:
            new_text = await prompt_filter(item.text)
            if new_text is None:
                return
            item = replace(item, text=new_text)
        self.put_nowait(item)

    @override
    def put_nowait(self, item: str | PendingUserMessage) -> None:
        """
        Inserts the input into the queue without running prompt filters,
        still notifies observers.
        """
        entry = PendingUserMessage(item) if isinstance(item, str) else item
        super().put_nowait(entry)
        self._call_all_on_change()

    @override
    async def get(self) -> PendingUserMessage:
        """Returns the latest item from the queue and notifies observers"""
        item = await super().get()
        self._call_all_on_change()
        return item

    async def drain(self) -> list[PendingUserMessage]:
        """
        Takes all messages from the queue and returns them oldest-first.
        Observers registered through `on_change` are only notified once,
        not per-message.
        """
        comments: list[PendingUserMessage] = []
        while True:
            try:
                comments.append(self.get_nowait())
            except asyncio.QueueEmpty:
                if comments:
                    # Don't notify about draining an empty queue
                    self._call_all_on_change()
                return comments
