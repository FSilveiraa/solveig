"""Queued messages display widget for Textual UI."""

from textual.containers import Vertical
from textual.widgets import Static

from solveig.interface.tui.collapsible import (
    CustomCollapsible,
)
from solveig.pending.user_message import PendingUserMessage
from solveig.pending.user_message_queue import UserMessageQueue


class PendingMessage(Static):
    """Single pending message item display."""

    def __init__(self, message: PendingUserMessage):
        super().__init__(classes="pending-message-item")
        self._message = message

    def compose(self):
        """Create the message item layout."""
        preview = self._message.text
        if len(preview) > 40:
            preview = preview[:37] + "..."
        yield Static(f"• {preview}", classes="pending-message-text")


class PendingMessages(Vertical):
    """Collapsible display for pending messages.

    Shows a count when collapsed, lists messages when expanded.
    Only visible when there are messages in the queue. Re-renders via the
    UserMessageQueue's `on_change` doorbell (self-registered at mount) - any mutation
    from any consumer, no per-call-site notification.
    """

    def __init__(self, queue: UserMessageQueue):
        super().__init__()
        self._queue = queue
        self._collapsible: CustomCollapsible
        self._content_container: Vertical

    def on_mount(self) -> None:
        # Self-register as a queue observer, any change to pending
        # messages re-renders the display
        self._queue.on_change(self.update_display)

    def compose(self):
        """Create the widget layout."""
        # Start hidden if no messages
        count = self._queue.qsize()
        self.styles.display = "none" if count == 0 else "block"

        # Create collapsible with custom title
        # Center section shows the message count, styled with theme color
        center = f"[$primary]{self._get_title()}[/]"
        self._collapsible = CustomCollapsible(
            left_collapsed="Message queue - Click to expand",
            left_expanded="Message queue - Click to collapse",
            center=center,
            right="",
            start_collapsed=True,
        )

        # Container for message items
        self._content_container = Vertical(classes="pending-messages-content")

        with self._collapsible:
            with self._content_container:
                for comment in self._queue.entries:
                    yield PendingMessage(comment)

    def _get_title(self) -> str:
        """Generate the collapsible title based on queue state."""
        count = self._queue.qsize()
        if count == 0:
            return "No messages pending"
        elif count == 1:
            return "1 message pending"
        else:
            return f"{count} messages pending"

    def _refresh_messages(self):
        """Refresh the message list display."""
        if self._content_container is None:
            return

        # Clear existing messages
        self._content_container.remove_children()

        # Add current user comments from queue
        for comment in self._queue.entries:
            self._content_container.mount(PendingMessage(comment))

    def update_display(self):
        """Update the display based on current queue state.

        Call this when the queue changes.
        """
        # Update visibility
        count = self._queue.qsize()
        self.styles.display = "block" if count > 0 else "none"

        if count > 0 and self._collapsible is not None:
            # Update title
            center = f"[$primary]{self._get_title()}[/]"
            self._collapsible.update_title(center=center)
            # Refresh message list
            self._refresh_messages()

    DEFAULT_CSS = """
        PendingMessages {
            height: auto;
            margin: 1 0 0 0;
            padding: 0;
            border-left: solid $input;
            border-top: solid $input;
            border-right: solid $input;
        }

        PendingMessages Collapsible {
            background: $background;
            border: none;
            margin: 0;
            padding: 0;
        }

        PendingMessages CollapsibleTitle {
            background: $background;
            color: $primary;
            padding: 0 1;
            margin: 0;
            height: 1;
        }

        PendingMessages CollapsibleTitle:hover {
            color: $accent;
        }

        PendingMessages .pending-messages-content {
            height: auto;
            margin: 0 0 0 1;
            padding: 0;
        }

        PendingMessages .pending-message-item {
            height: 1;
            margin: 0;
            padding: 0;
        }

        PendingMessages .pending-message-text {
            color: $foreground;
            text-style: dim;
        }
        """
