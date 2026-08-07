"""Interactive tree display widget for directory structures.

Lazy expansion: the tree is built shallowly (root + first level) from the
already-read ``FileMetadata``.  Deeper levels are populated on demand when a
branch is expanded, reading children from the ``FileMetadata`` stored on each
``TreeNode`` — the filesystem is never touched again.  This keeps the cost
proportional to what the user actually looks at instead of the total size of
the scanned tree (an eager build of a 5k-file directory would materialise 5k
Textual nodes up front).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePath

from pydantic import ByteSize
from textual.widgets import Tree

from solveig.utils.file import FileMetadata


class TreeDisplay(Tree):
    """Interactive tree widget that displays directory structures from
    ``FileMetadata`` with lazy expansion.

    Satisfies the ``TreeBox`` protocol structurally — a Textual widget cannot
    inherit a Protocol (unrelated metaclasses); ``interface.py`` declares this
    is what ``display_tree`` returns, and that is where it is checked.
    ``replace`` is defined below; ``refresh`` is Textual's own, inherited, so
    the signature mypy checks against the protocol is the real one.

    The full metadata tree is already read (the filesystem operation happened
    before the interface call).  At construction only the root and its first
    level of children are rendered; deeper levels are added when the user
    expands a branch, sourcing children from the ``FileMetadata`` stored on
    each node.  No filesystem calls happen after construction.

    Parameters
    ----------
    metadata:
        Root ``FileMetadata`` to display.  Its ``listing`` is the source of
        truth for the entire tree.
    display_metadata:
        When true, each node label also shows size / modified time.
    expand_root:
        Expand the root node by default so its first level is visible.
    max_depth:
        Initial render depth limit.  ``<= 0`` (e.g. the default ``-1``) means
        "unlimited" — only the root and its immediate children are rendered
        initially and everything deeper is lazy.  ``> 0`` pre-renders (and
        auto-expands) down to that depth; nodes below it are still created as
        expandable branches whose children load lazily on expand.
    """

    def __init__(
        self,
        metadata: FileMetadata,
        display_metadata: bool = False,
        expand_root: bool = True,
        max_depth: int = -1,
        **kwargs,
    ):
        self._display_metadata = display_metadata
        self._max_depth = max_depth
        # TreeNode ids whose children have already been materialised.  Tracked
        # on the widget (not on the nodes) so ``replace()`` can reset the set
        # and so we don't rely on ``TreeNode`` allowing arbitrary attributes.
        self._populated: set[int] = set()

        super().__init__(self._format_node_label(metadata, display_metadata), **kwargs)

        # The root node carries its own metadata so lazy expansion can read it
        # back without touching the filesystem.
        self.root.data = metadata
        self._build_initial(self.root, metadata, depth=0)

        if expand_root:
            self.root.expand()

    # ------------------------------------------------------------------ #
    # Public API (TreeBox contract)
    # ------------------------------------------------------------------ #

    def replace(self, metadata: FileMetadata) -> None:
        """Rebuild the tree from new ``FileMetadata``."""
        self._populated.clear()
        self.reset(
            self._format_node_label(metadata, self._display_metadata),
            data=metadata,
        )
        self._build_initial(self.root, metadata, depth=0)
        self.root.expand()
        self.refresh(layout=True)

    # ------------------------------------------------------------------ #
    # Label formatting
    # ------------------------------------------------------------------ #

    def _format_node_label(
        self, metadata: FileMetadata, display_metadata: bool = False
    ) -> str:
        """Format a node label from metadata, matching current tree display format."""
        icon = "🗁" if metadata.is_directory else "🗎"
        name = PurePath(metadata.path).name
        label = f"{icon} {name}"

        if display_metadata:
            if not metadata.is_directory:
                size_str = ByteSize(metadata.size).human_readable()
                label += f"  |  size: {size_str}"

            if metadata.modified_time:
                modified_time = datetime.fromtimestamp(
                    float(metadata.modified_time)
                ).isoformat()
                label += f"  |  modified: {modified_time}"

        return label

    # ------------------------------------------------------------------ #
    # Lazy population
    # ------------------------------------------------------------------ #

    def _populate_node(self, node, metadata: FileMetadata) -> None:
        """Materialise one level of ``node``'s children from ``metadata``.

        Idempotent — repeated calls for an already-populated node are no-ops
        (tracked via ``self._populated``).  Children that are directories with
        listings become expandable branches (their own children are *not*
        populated here); files and empty directories become leaves.
        """
        if node.id in self._populated:
            return
        self._populated.add(node.id)

        if not metadata or not metadata.is_directory or not metadata.listing:
            return

        # NOTE: no filtering here. An ignored path is pruned by
        # `Filesystem.read_metadata` before it ever becomes metadata, so a
        # listing that reached this widget is already the whole truth.
        for _sub_path, sub_metadata in sorted(metadata.listing.items()):
            label = self._format_node_label(sub_metadata, self._display_metadata)

            if sub_metadata.is_directory and sub_metadata.listing:
                # Expandable branch — children load lazily on expand.
                node.add(label, data=sub_metadata, expand=False, allow_expand=True)
            else:
                # File or empty directory — leaf.
                node.add_leaf(label, data=sub_metadata)

    def _build_initial(self, node, metadata: FileMetadata, depth: int) -> None:
        """Initial (shallow) build, optionally pre-rendering deeper levels.

        Always populates ``node``'s direct children.  When ``max_depth > 0``
        and the next level is still within the limit, recurse into each child
        branch and auto-expand it so the pre-rendered levels are visible up
        front.  Levels at or beyond ``max_depth`` stay as collapsed lazy
        branches (still expandable on click).
        """
        self._populate_node(node, metadata)

        if self._max_depth <= 0:
            # Unlimited → shallow: only the root's first level is rendered,
            # everything deeper is lazy.
            return

        if depth + 1 >= self._max_depth:
            return

        for child in list(node.children):
            child_metadata = child.data
            if not isinstance(child_metadata, FileMetadata):
                continue
            if child_metadata.is_directory and child_metadata.listing:
                self._build_initial(child, child_metadata, depth + 1)
                child.expand()

    # ------------------------------------------------------------------ #
    # Textual message handling
    # ------------------------------------------------------------------ #

    def on_node_expanded(self, event: Tree.NodeExpanded) -> None:
        """Lazy-populate a branch when the user expands it."""
        node = event.node
        metadata = node.data
        if isinstance(metadata, FileMetadata):
            self._populate_node(node, metadata)

    # ------------------------------------------------------------------ #
    # CSS
    # ------------------------------------------------------------------ #

    @classmethod
    def get_css(cls) -> str:
        """Generate CSS for tree display."""
        return """
        TreeDisplay {
            border: solid $box;
            background: $background;
            color: $foreground;
            margin: 1;
            padding: 0 1;
            height: auto;
        }

        TreeDisplay > .tree--guides {
            color: $foreground;
        }

        TreeDisplay > .tree--label {
            color: $foreground;
        }
        """
