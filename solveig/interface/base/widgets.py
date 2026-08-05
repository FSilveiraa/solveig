"""Abstract box contracts returned by interface display methods.

Each is a handle the caller holds after the interface creates and mounts the
box. The caller can call `replace()` to swap the contents — the frontend's
widget re-renders. User interaction (clicking, expanding) is implementation-
internal; the contract only covers "caller can update the content."

- `TextBox`      — editable text (append, clear, replace)
- `DiffBox`      — read-only comparison (replace old + new)
- `TreeBox`      — directory tree from metadata (replace metadata)
- `EditableMessage` — message widget hosting Edit/Retry/Delete/Branch buttons
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solveig.utils.file import FileMetadata


class TextBox:
    def append(self, text: str) -> None:
        """Append text to the end of the box."""

    def clear(self) -> None:
        """Empty the box content."""

    def replace(self, text: str) -> None:
        """Replace the entire content of the box."""


class DiffBox:
    """A diff comparison between two versions of content.

    Not interactive — a diff is a static comparison. The caller can replace
    the old/new content to re-render with different inputs.
    """

    def replace(self, old_content: str, new_content: str) -> None:
        """Replace both sides of the diff."""


class TreeBox:
    """A directory tree backed by FileMetadata.

    The full metadata is already read (the filesystem operation happened
    before the interface call). The tree renders lazily — shallow initially,
    filling in as the user expands nodes. All interaction (expand, collapse,
    lazy rendering) is handled internally by the frontend; the contract only
    exposes content replacement.
    """

    def replace(self, metadata: FileMetadata) -> None:
        """Replace the tree with new metadata."""

    def refresh(self) -> None:
        """Redraw the tree. No-op by default."""


class EditableMessage:
    """What a message widget must implement to host action buttons
    (Edit/Retry/Delete/Branch)."""

    async def begin_edit(self) -> None:
        """Prompt for replacement text and overwrite this message in place."""

    async def retry(self) -> None:
        """Drop this message and everything after it, then resubmit its
        text as a fresh prompt."""

    async def delete_from_here(self) -> None:
        """Drop this message and everything after it."""

    async def branch_from_here(self) -> None:
        """Store the current conversation as a checkpoint, then drop this
        message and everything after it."""
