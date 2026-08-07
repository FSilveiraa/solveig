"""Box contracts returned by interface display methods.

Each is a handle the caller holds after the interface creates and mounts the
box. The caller can call `replace()` to swap the contents — the frontend's
widget re-renders. User interaction (clicking, expanding) is implementation-
internal; the contract only covers "caller can update the content."

- `TextBox`      — editable text (append, clear, replace)
- `DiffBox`      — read-only comparison (replace old + new)
- `TreeBox`      — directory tree from metadata (replace metadata)
- `EditableMessage` — message widget hosting Edit/Retry/Delete/Branch buttons

All four are `Protocol`s, for the same reason `ConversationObserver` is: a
contract with a default implementation is not a contract. As plain classes
with empty bodies, a frontend that forgot a method got silence at runtime
instead of an error. Structural typing makes "satisfies the contract"
checkable at the boundary — where the interface declares it returns a
`TextBox`, where a button declares it drives an `EditableMessage`.

A `Protocol` rather than an ABC because `EditableMessage`'s implementer IS a
Textual widget: Textual's `_MessagePumpMeta` and `ABCMeta` are unrelated
metaclasses, so a widget physically cannot take one of these as a second base.

Which half inherits, and why it matters:

- `TextBox`, `DiffBox`, `TreeBox` are inherited EXPLICITLY. Their implementers
  (`CollapsibleTextBox`, `CollapsibleDiffBox`, `FileTree`) own a widget rather
  than being one, so there is no metaclass conflict — and mypy then checks
  conformance at the class definition instead of only where `interface.py`
  annotates a return type. That distinction is not academic: `TreeBox.refresh`
  was once widened to `(*args, **kwargs) -> object` to accommodate a Textual
  widget's fluent `refresh`, and a return-site check had nothing to object to.
- `EditableMessage` is NOT inherited; conformance stays structural. Its
  implementer (`EditableComment`) is a Textual widget by design — it is not a
  handle passed across the boundary, it is the widget hosting its own buttons.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from solveig.utils.file import FileMetadata


@runtime_checkable
class TextBox(Protocol):
    """Editable text a caller keeps a handle on after the interface mounts it."""

    def append(self, text: str) -> None:
        """Append text to the end of the box."""
        ...

    def clear(self) -> None:
        """Empty the box content."""
        ...

    def replace(self, text: str) -> None:
        """Replace the entire content of the box."""
        ...


@runtime_checkable
class DiffBox(Protocol):
    """A diff comparison between two versions of content.

    Not interactive — a diff is a static comparison. The caller can replace
    the old/new content to re-render with different inputs.
    """

    def replace(self, old_content: str, new_content: str) -> None:
        """Replace both sides of the diff."""
        ...


@runtime_checkable
class TreeBox(Protocol):
    """A directory tree backed by FileMetadata.

    The full metadata is already read (the filesystem operation happened
    before the interface call). The tree renders lazily — shallow initially,
    filling in as the user expands nodes. All interaction (expand, collapse,
    lazy rendering) is handled internally by the frontend; the contract only
    exposes content replacement.
    """

    def replace(self, metadata: FileMetadata) -> None:
        """Replace the tree with new metadata."""
        ...

    def refresh(self) -> None:
        """Redraw the tree after an out-of-band mutation.

        The one member here a frontend may legitimately leave as a no-op: a
        frontend that redraws on its own has nothing to do. It stays on the
        contract because a caller that DID mutate out of band needs somewhere
        to say so.
        """
        ...


@runtime_checkable
class EditableMessage(Protocol):
    """What a message widget must implement to host action buttons
    (Edit/Retry/Delete/Branch)."""

    async def begin_edit(self) -> None:
        """Prompt for replacement text and overwrite this message in place."""
        ...

    async def retry(self) -> None:
        """Drop this message and everything after it, then resubmit its
        text as a fresh prompt."""
        ...

    async def delete_from_here(self) -> None:
        """Drop this message and everything after it."""
        ...

    async def branch_from_here(self) -> None:
        """Store the current conversation as a checkpoint, then drop this
        message and everything after it."""
        ...
