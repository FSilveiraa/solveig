"""TreeRequirement plugin - Generate directory tree listings."""

from __future__ import annotations

from pathlib import PurePath
from typing import Literal

from pydantic import Field, field_validator

from solveig.interface import SolveigInterface

# Import the registration decorator
from solveig.schema import register_requirement
from solveig.schema.requirements.base import Requirement, validate_non_empty_path
from solveig.schema.results.base import RequirementResult
from solveig.utils.file import Filesystem, Metadata


class TreeResult(RequirementResult):
    path: str | PurePath
    metadata: Metadata | None  # Complete tree metadata


@register_requirement
class TreeRequirement(Requirement):
    """Generate a directory tree listing showing file structure."""

    title: Literal["tree"] = "tree"
    path: str = Field(..., description="Directory path to generate tree for")
    max_depth: int = Field(
        default=-1, description="Maximum depth to explore (-1 for full tree)"
    )

    @field_validator("path")
    @classmethod
    def path_not_empty(cls, path: str) -> str:
        return validate_non_empty_path(path)

    def create_error_result(self, error_message: str, accepted: bool) -> TreeResult:
        """Create TreeResult with error."""
        return TreeResult(
            requirement=self,
            path=Filesystem.get_absolute_path(self.path),
            accepted=accepted,
            error=error_message,
            metadata=None,
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of tree capability."""
        return (
            "tree(path): generates a directory tree structure showing files and folders"
        )

    def actually_solve(self, config, interface: SolveigInterface) -> TreeResult:
        abs_path = Filesystem.get_absolute_path(self.path)

        # Get complete tree metadata using new approach
        metadata = Filesystem.read_metadata(abs_path, descend_level=self.max_depth)

        # Display the tree structure
        interface.display_tree(
            metadata=metadata, display_metadata=False, title=f"Tree: {abs_path}"
        )

        return TreeResult(
            requirement=self,
            accepted=True,
            path=abs_path,
            metadata=metadata,
        )


# Fix possible forward typing references
TreeResult.model_rebuild()
