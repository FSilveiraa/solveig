"""Delete requirement - allows LLM to delete files and directories."""

from typing import TYPE_CHECKING, Literal

from pydantic import Field, field_validator

from solveig.utils.file import Filesystem

from .base import Requirement, validate_non_empty_path

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

    async def display_header(self, interface: "SolveigInterface") -> None:
        """Display delete requirement header."""
        await super().display_header(interface)
        await interface.display_file_info(source_path=self.path)
        # abs_path = Filesystem.get_absolute_path(self.path)
        # path_info = format_path_info(
        #     path=self.path, abs_path=abs_path, is_dir=await Filesystem.is_dir(abs_path)
        # )
        # await interface.display_text(path_info)
        await interface.display_warning(
            "This operation is permanent and cannot be undone!"
        )

    def create_error_result(self, error_message: str, accepted: bool) -> "DeleteResult":
        """Create DeleteResult with error."""
        return DeleteResult(
            requirement=self,
            path=str(Filesystem.get_absolute_path(self.path)),
            accepted=accepted,
            error=error_message,
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of delete capability."""
        return "delete(comment, path): permanently deletes a file or directory"

    async def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "DeleteResult":
        # Pre-flight validation - use utils/file.py validation
        abs_path = Filesystem.get_absolute_path(self.path)

        try:
            await Filesystem.validate_delete_access(abs_path)
        except (FileNotFoundError, PermissionError) as e:
            await interface.display_error(f"Skipping: {e}")
            return DeleteResult(
                requirement=self, accepted=False, error=str(e), path=str(abs_path)
            )

        auto_delete = Filesystem.path_matches_patterns(
            abs_path, config.auto_allowed_paths
        )
        if auto_delete:
            await interface.display_text(
                f"Deleting {abs_path} since it matches config.auto_allowed_paths"
            )

        # Get user consent (with extra warning)
        elif not await interface.ask_yes_no(f"Permanently delete {abs_path}? [y/N]: "):
            return DeleteResult(requirement=self, accepted=False, path=str(abs_path))

        try:
            # Perform the delete operation - use utils/file.py method
            await Filesystem.delete(abs_path)
            await interface.display_success("Deleted")
            return DeleteResult(requirement=self, path=str(abs_path), accepted=True)
        except (PermissionError, OSError) as e:
            await interface.display_error(f"Found error when deleting: {e}")
            return DeleteResult(
                requirement=self, accepted=False, error=str(e), path=str(abs_path)
            )
