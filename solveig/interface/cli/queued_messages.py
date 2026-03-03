"""Queued messages display widget for Textual UI."""

from typing import TYPE_CHECKING

from textual.containers import Vertical
from textual.widgets import Collapsible, Static

from solveig.interface.themes import Palette

if TYPE_CHECKING:
    from solveig.schema.message.pending import PendingMessageQueue
    from solveig.schema.message.user import UserComment


class QueuedMessageItem(Static):
    """Single queued message item display."""

    def __init__(self, comment: "UserComment", **kwargs):
        self._comment = comment
        super().__init__(**kwargs)

    def compose(self):
        """Create the message item layout."""
        preview = self._comment.comment
        if len(preview) > 40:
            preview = preview[:37] + "..."
        yield Static(f"• {preview}", classes="queued-message-text")


class QueuedMessagesDisplay(Vertical):
    """Collapsible display for queued messages.

    Shows a count when collapsed, lists messages when expanded.
    Only visible when there are messages in the queue.
    """

    def __init__(self, queue: "PendingMessageQueue", theme: Palette, **kwargs):
        self._queue = queue
        self._theme = theme
        self._collapsible: Collapsible | None = None
        self._content_container: Vertical | None = None
        super().__init__(**kwargs)

    def compose(self):
        """Create the widget layout."""
        # Start hidden if no messages
        count = self._queue.count_user_comments()
        self.styles.display = "none" if count == 0 else "block"

        # Create collapsible with custom title
        self._collapsible = Collapsible(
            title=self._get_title(),
            collapsed=False,  # Start expanded to show messages
        )

        # Container for message items
        self._content_container = Vertical(classes="queued-messages-content")

        with self._collapsible:
            yield self._content_container

        # Initial population
        self._refresh_messages()

    def _get_title(self) -> str:
        """Generate the collapsible title based on queue state."""
        count = self._queue.count_user_comments()
        if count == 0:
            return "No messages queued"
        elif count == 1:
            return "1 message queued"
        else:
            return f"{count} messages queued"

    def _refresh_messages(self):
        """Refresh the message list display."""
        if self._content_container is None:
            return

        # Clear existing messages
        self._content_container.remove_children()

        # Add current user comments from queue
        for comment in self._queue.get_user_comments():
            self._content_container.mount(
                QueuedMessageItem(comment, classes="queued-message-item")
            )

    def update_display(self):
        """Update the display based on current queue state.

        Call this when the queue changes.
        """
        # Update visibility
        count = self._queue.count_user_comments()
        self.styles.display = "block" if count > 0 else "none"

        if count > 0 and self._collapsible is not None:
            # Update title
            self._collapsible.title = self._get_title()
            # Refresh message list
            self._refresh_messages()

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        """Generate CSS for the queued messages widget."""
        return f"""
        QueuedMessagesDisplay {{
            height: auto;
            margin: 1 0 0 0;
            padding: 0;
            border-left: heavy {theme.info};
            border-top: heavy {theme.info};
        }}

        QueuedMessagesDisplay Collapsible {{
            background: {theme.background};
            border: none;
            margin: 0;
            padding: 0;
        }}

        QueuedMessagesDisplay CollapsibleTitle {{
            background: {theme.background};
            color: {theme.info};
            padding: 0;
            margin: 0;
            height: 1;
        }}

        QueuedMessagesDisplay CollapsibleTitle:hover {{
            color: {theme.section};
        }}

        QueuedMessagesDisplay .queued-messages-content {{
            height: auto;
            margin: 0 0 0 1;
            padding: 0;
        }}

        QueuedMessagesDisplay .queued-message-item {{
            height: 1;
            margin: 0;
            padding: 0;
        }}

        QueuedMessagesDisplay .queued-message-text {{
            color: {theme.text};
            text-style: dim;
        }}
        """
