"""Status bar widget with spinner animation support."""

import os.path
import time
from os import PathLike

from textual.widgets import Static


class StatusBar(Static):
    """Status bar showing current application state with Rich spinner support."""

    def __init__(self, **kwargs):
        super().__init__("Initializing", **kwargs)
        self._status = "Initializing"
        self._tokens = "0↑ / 0↓"
        self._model = ""
        self._url = ""
        self._spinner = None
        self._timer = None
        self._path = os.getcwd()

    def update_status_info(
        self,
        status: str | None = None,
        tokens: tuple[int, int] | int | str | None = None,
        model: str | None = None,
        url: str | None = None,
        path: str | PathLike | None = None,
    ):
        """Update status bar with multiple pieces of information."""
        if status is not None:
            self._status = status
        if tokens is not None:
            if isinstance(tokens, tuple):
                # tokens is (sent, received)
                self._tokens = f"{tokens[0]}↑ / {tokens[1]}↓"
            else:
                self._tokens = tokens
        if model is not None:
            self._model = model
        if url is not None:
            self._url = url
        if path is not None:
            self._path = path

        self._refresh_display()

    def _refresh_display(self):
        """Refresh the status bar display with dynamic sections."""
        status_text = self._status

        if self._spinner:
            frame = self._spinner.render(time.time())
            # Convert Rich text to plain string
            spinner_char = frame.plain if hasattr(frame, "plain") else str(frame)
            status_text = f"{spinner_char} {status_text}"

        # Build sections only for fields that have content
        sections = [status_text]  # Status always shown

        if self._tokens:
            sections.append(f"{self._tokens}")
        if self._url:
            sections.append(f"{self._url}")
        if self._model:
            sections.append(f"{self._model}")
        if self._path:
            sections.append(self._path)

        # Get terminal width
        try:
            total_width = self.app.size.width if hasattr(self, "app") else 80
        except AttributeError:
            total_width = 80

        # Calculate section width
        section_width = total_width // len(sections)

        # Format each section to fit its allocated width
        formatted_sections = []
        for section in sections:
            if len(section) > section_width - 1:
                formatted = section[: section_width - 4] + "..."
            else:
                formatted = section.center(section_width - 1)
            formatted_sections.append(formatted)

        # Join with separators
        display_text = "│".join(formatted_sections)
        self.update(display_text)