"""Delete requirement - allows LLM to delete files and directories."""

from typing import TYPE_CHECKING, Literal

from pydantic import Field, field_validator

from solveig.utils.file import Filesystem

from .base import Requirement, format_path_info, validate_non_empty_path

if TYPE_CHECKING:
    from solveig.config import SolveigConfig
    from solveig.interface import SolveigInterface
    from solveig.schema.results import DeleteResult
else:
    from solveig.schema.results import DeleteResult


class DeleteRequirement(Requirement):
    title: Literal["delete"] = "delete"
    path: str = Field(
        ...,
        description="Path of file/directory to permanently delete (supports ~ for home directory)",
    )

    @field_validator("path", mode="before")
    @classmethod
    def path_not_empty(cls, path: str) -> str:
        return validate_non_empty_path(path)

    def display_header(
        self, interface: "SolveigInterface", detailed: bool = False
    ) -> None:
        """Display delete requirement header."""
        super().display_header(interface)
        abs_path = Filesystem.get_absolute_path(self.path)
        path_info = format_path_info(
            path=self.path, abs_path=abs_path, is_dir=Filesystem.is_dir(abs_path)
        )
        interface.display_text(path_info)
        interface.display_warning("This operation is permanent and cannot be undone!")

    def create_error_result(self, error_message: str, accepted: bool) -> "DeleteResult":
        """Create DeleteResult with error."""
        return DeleteResult(
            requirement=self,
            path=Filesystem.get_absolute_path(self.path),
            accepted=accepted,
            error=error_message,
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of delete capability."""
        return "delete(path): permanently deletes a file or directory"

    def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "DeleteResult":
        # Pre-flight validation - use utils/file.py validation
        abs_path = Filesystem.get_absolute_path(self.path)

        try:
            Filesystem.validate_delete_access(abs_path)
        except (FileNotFoundError, PermissionError) as e:
            interface.display_error(f"Skipping: {e}")
            return DeleteResult(
                requirement=self, accepted=False, error=str(e), path=abs_path
            )

        metadata = Filesystem.read_metadata(abs_path)
        interface.display_tree(metadata=metadata)

        auto_delete = Filesystem.path_matches_patterns(
            abs_path, config.auto_allowed_paths
        )
        if auto_delete:
            interface.display_text(
                f"Deleting {abs_path} since it matches config.auto_allowed_paths"
            )

        # Get user consent (with extra warning)
        elif not interface.ask_yes_no(f"Permanently delete {abs_path}? [y/N]: "):
            return DeleteResult(requirement=self, accepted=False, path=abs_path)

        try:
            # Perform the delete operation - use utils/file.py method
            Filesystem.delete(abs_path)
            with interface.with_indent():
                interface.display_success("Deleted")
            return DeleteResult(requirement=self, path=abs_path, accepted=True)
        except (PermissionError, OSError) as e:
            interface.display_error(f"Found error when deleting: {e}")
            return DeleteResult(
                requirement=self, accepted=False, error=str(e), path=abs_path
            )
