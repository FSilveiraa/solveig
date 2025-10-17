"""TreeRequirement plugin - Generate directory tree listings."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from solveig.interface import SolveigInterface

# Import the registration decorator directly
from solveig.schema import register_requirement
from solveig.schema.requirements.base import (
    Requirement,
    validate_non_empty_path,
)
from solveig.schema.results.base import RequirementResult
from solveig.utils.file import Filesystem, Metadata


class TreeResult(RequirementResult):
    title: Literal["tree"] = "tree"
    path: str
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

    async def display_header(
        self, interface: SolveigInterface, detailed: bool = False
    ) -> None:
        """Display tree requirement header."""
        await super().display_header(interface)
        await interface.display_file_info(source_path=self.path)
        # abs_path = Filesystem.get_absolute_path(self.path)
        # is_dir = await Filesystem.is_dir(abs_path)
        # path_info = format_path_info(path=self.path, abs_path=abs_path, is_dir=is_dir)
        # await interface.display_text(path_info)

    def create_error_result(self, error_message: str, accepted: bool) -> TreeResult:
        """Create TreeResult with error."""
        return TreeResult(
            requirement=self,
            path=str(Filesystem.get_absolute_path(self.path)),
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

    async def actually_solve(self, config, interface: SolveigInterface) -> TreeResult:
        abs_path = Filesystem.get_absolute_path(self.path)

        if await interface.ask_yes_no("Allow reading tree?"):
            # Get complete tree metadata using new approach
            metadata = await Filesystem.read_metadata(
                abs_path, descend_level=self.max_depth
            )

            # Display the tree structure
            await interface.display_tree(
                metadata=metadata, display_metadata=False, title=f"Tree: {abs_path}"
            )

            if (
                Filesystem.path_matches_patterns(abs_path, config.auto_allowed_paths)
                or config.auto_send
            ):
                accepted = True
                await interface.display_text(
                    f"Sending tree since {"config.auto_send=True" if config.auto_send else f"{abs_path} matches config.allow_allowed_paths"}"
                )
            else:
                accepted = await interface.ask_yes_no("Allow sending tree?")
            if accepted:
                return TreeResult(
                    requirement=self,
                    accepted=True,
                    path=str(abs_path),
                    metadata=metadata,
                )

        return TreeResult(
            requirement=self,
            accepted=False,
            path=str(abs_path),
            metadata=None,
        )


# Fix possible forward typing references
TreeResult.model_rebuild()
