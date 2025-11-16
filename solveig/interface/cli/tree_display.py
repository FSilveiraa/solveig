"""Interactive tree display widget for directory structures."""

from datetime import datetime
from pathlib import PurePath

from textual.widgets import Tree

from solveig.interface.themes import Palette
from solveig.utils.file import Metadata
from solveig.utils.misc import convert_size_to_human_readable


class TreeDisplay(Tree):
    """
    Interactive tree widget that displays directory structures from Metadata.

    Unlike DirectoryTree, this builds a complete static tree from existing
    Metadata without on-demand loading, ensuring consistent display regardless
    of user interaction.
    """

    def __init__(self, metadata: Metadata, display_metadata: bool = False, **kwargs):
        # Create tree with root node
        super().__init__(self._format_node_label(metadata, display_metadata), **kwargs)
        self._display_metadata = display_metadata

        # Build the complete tree structure from metadata
        self._build_tree_from_metadata(self.root, metadata)

        # Expand root by default to show content
        self.root.expand()

    def _format_node_label(self, metadata: Metadata, display_metadata: bool = False) -> str:
        """Format a node label from metadata, matching current tree display format."""
        icon = "🗁" if metadata.is_directory else "🗎"
        name = PurePath(metadata.path).name
        label = f"{icon} {name}"

        if display_metadata:
            if not metadata.is_directory:
                size_str = convert_size_to_human_readable(metadata.size)
                label += f"  |  size: {size_str}"

            if metadata.modified_time:
                modified_time = datetime.fromtimestamp(
                    float(metadata.modified_time)
                ).isoformat()
                label += f"  |  modified: {modified_time}"

        return label

    def _build_tree_from_metadata(self, parent_node, metadata: Metadata):
        """Recursively build tree nodes from metadata structure."""
        if not metadata.is_directory or not metadata.listing:
            return

        # Sort entries for consistent ordering (same as current implementation)
        sorted_entries = sorted(metadata.listing.items())

        for _sub_path, sub_metadata in sorted_entries:
            label = self._format_node_label(sub_metadata, self._display_metadata)

            if sub_metadata.is_directory and sub_metadata.listing:
                # Directory with children - create expandable node
                child_node = parent_node.add(label, expand=True)
                # Recursively add children
                self._build_tree_from_metadata(child_node, sub_metadata)
            else:
                # File or empty directory - create leaf node
                parent_node.add_leaf(label)

    @classmethod
    def get_css(cls, theme: Palette) -> str:
        """Generate CSS for tree display."""
        return f"""
        TreeDisplay {{
            border: solid {theme.box};
            background: {theme.background};
            color: {theme.text};
            margin: 1;
            padding: 0 1;
            height: auto;
        }}

        TreeDisplay > .tree--guides {{
            color: {theme.text};
        }}

        TreeDisplay > .tree--label {{
            color: {theme.text};
        }}
        """