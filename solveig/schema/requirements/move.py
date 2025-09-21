"""Move requirement - allows LLM to move files and directories."""

from typing import TYPE_CHECKING, Literal

from pydantic import Field, field_validator

from solveig.utils.file import Filesystem

from .base import Requirement, format_path_info, validate_non_empty_path

if TYPE_CHECKING:
    from solveig.config import SolveigConfig
    from solveig.interface import SolveigInterface
    from solveig.schema.results import MoveResult
else:
    from solveig.schema.results import MoveResult


class MoveRequirement(Requirement):
    title: Literal["move"] = "move"
    source_path: str = Field(
        ...,
        description="Current path of file/directory to move (supports ~ for home directory)",
    )
    destination_path: str = Field(
        ..., description="New path where file/directory should be moved to"
    )

    @field_validator("source_path", "destination_path", mode="before")
    @classmethod
    def validate_paths(cls, path: str) -> str:
        return validate_non_empty_path(path)

    def display_header(
        self, interface: "SolveigInterface", detailed: bool = False
    ) -> None:
        """Display move requirement header."""
        super().display_header(interface)
        source_abs = Filesystem.get_absolute_path(self.source_path)
        dest_abs = Filesystem.get_absolute_path(self.destination_path)
        path_info = format_path_info(
            path=self.source_path,
            abs_path=source_abs,
            is_dir=Filesystem.is_dir(source_abs),
            destination_path=self.destination_path,
            absolute_destination_path=dest_abs,
        )
        interface.display_text(path_info)

    def create_error_result(self, error_message: str, accepted: bool) -> "MoveResult":
        """Create MoveResult with error."""
        return MoveResult(
            requirement=self,
            accepted=accepted,
            error=error_message,
            source_path=Filesystem.get_absolute_path(self.source_path),
            destination_path=Filesystem.get_absolute_path(self.destination_path),
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of move capability."""
        return "move(source_path, destination_path): moves a file or directory"

    def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "MoveResult":
        # Pre-flight validation - use utils/file.py validation
        abs_source_path = Filesystem.get_absolute_path(self.source_path)
        abs_destination_path = Filesystem.get_absolute_path(self.destination_path)
        error: Exception | None = None

        try:
            Filesystem.validate_read_access(abs_source_path)
            Filesystem.validate_write_access(abs_destination_path)
        except Exception as e:
            interface.display_error(f"Skipping: {e}")
            return MoveResult(
                requirement=self,
                accepted=False,
                error=str(e),
                source_path=abs_source_path,
                destination_path=abs_destination_path,
            )

        source_metadata = Filesystem.read_metadata(abs_source_path)
        interface.display_tree(metadata=source_metadata, title="Source Metadata")

        # Get user consent
        if (
            Filesystem.path_matches_patterns(abs_source_path, config.auto_allowed_paths)
            and Filesystem.path_matches_patterns(
                abs_destination_path, config.auto_allowed_paths
            )
        ) or interface.ask_yes_no(
            f"Allow moving {abs_source_path} to {abs_destination_path}? [y/N]: "
        ):
            try:
                # Perform the move operation - use utils/file.py method
                Filesystem.move(abs_source_path, abs_destination_path)

                with interface.with_indent():
                    interface.display_success("Moved")
                return MoveResult(
                    requirement=self,
                    accepted=True,
                    source_path=abs_source_path,
                    destination_path=abs_destination_path,
                )
            except (PermissionError, OSError, FileExistsError) as e:
                interface.display_error(f"Found error when moving: {e}")
                return MoveResult(
                    requirement=self,
                    accepted=False,
                    error=str(e),
                    source_path=abs_source_path,
                    destination_path=abs_destination_path,
                )
        else:
            return MoveResult(
                requirement=self,
                accepted=False,
                source_path=abs_source_path,
                destination_path=abs_destination_path,
                error=str(error) if error else None,
            )
