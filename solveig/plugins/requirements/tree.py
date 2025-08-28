"""TreeRequirement plugin - Generate directory tree listings."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field, field_validator

from solveig.schema.requirements.base import Requirement, validate_non_empty_path
from solveig.utils.file import Filesystem

# Import the registration decorator
from . import register_plugin_result, register_requirement

if TYPE_CHECKING:
    from solveig.interface import SolveigInterface


@register_requirement
class TreeRequirement(Requirement):
    """Generate a directory tree listing showing file structure."""

    title: Literal["tree"] = "tree"
    path: str = Field(..., description="Directory path to generate tree for")

    @field_validator("path")
    @classmethod
    def path_not_empty(cls, path: str) -> str:
        return validate_non_empty_path(path)

    def create_error_result(self, error_message: str, accepted: bool) -> TreeResult:
        """Create TreeResult with error."""
        from solveig.schema.results.tree import TreeResult

        return TreeResult(
            requirement=self,
            path=Filesystem.get_absolute_path(self.path),
            accepted=accepted,
            error=error_message,
            tree_output="",
            total_files=0,
            total_dirs=0,
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of tree capability."""
        return (
            "tree(path): generates a directory tree structure showing files and folders"
        )

    def _actually_solve(self, config, interface: SolveigInterface) -> TreeResult:
        from solveig.schema.results.tree import TreeResult

        abs_path = Filesystem.get_absolute_path(self.path)

        # Walk directory tree and collect all files/dirs
        stats = {"files": 0, "dirs": 0}
        self._walk_and_display(interface, abs_path, stats)

        return TreeResult(
            requirement=self,
            accepted=True,
            path=abs_path,
            tree_output="",
            total_files=stats["files"],
            total_dirs=stats["dirs"],
        )

    def _walk_and_display(
        self, interface: SolveigInterface, path: Path, stats: dict
    ) -> None:
        """Walk directory tree using existing utilities and display via interface."""
        try:
            metadata = Filesystem.read_metadata(path)

            if Filesystem._is_dir(path):
                # Get directory listing - includes all files and dirs, including hidden
                listing = Filesystem.get_dir_listing(path)
                stats["dirs"] += 1

                # Display this directory and its immediate children
                interface.display_tree(
                    metadata=metadata, listing=listing, title=f"Tree: {path}"
                )

                # Count files in this level
                for entry_path, entry_metadata in listing.items():
                    if entry_metadata.is_directory:
                        # Recursively walk subdirectories
                        self._walk_and_display(interface, entry_path, stats)
                    else:
                        stats["files"] += 1
            else:
                # Single file
                stats["files"] += 1
                interface.display_tree(
                    metadata=metadata, listing=None, title=f"File: {path}"
                )

        except (PermissionError, OSError) as e:
            interface.display_error(f"Cannot access {path}: {e}")


# Register the TreeResult for model rebuilding
from solveig.schema.results.tree import TreeResult

register_plugin_result(TreeResult)
