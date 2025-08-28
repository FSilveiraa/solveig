"""Copy requirement - allows LLM to copy files and directories."""

from typing import TYPE_CHECKING, Literal

from pydantic import Field, field_validator

from solveig.utils.file import Filesystem

from .base import Requirement, format_path_info, validate_non_empty_path

if TYPE_CHECKING:
    from solveig.config import SolveigConfig
    from solveig.interface import SolveigInterface
    from solveig.schema.results import CopyResult
else:
    from solveig.schema.results import CopyResult


class CopyRequirement(Requirement):
    title: Literal["copy"] = "copy"
    source_path: str = Field(
        ...,
        description="Path of file/directory to copy from (supports ~ for home directory)",
    )
    destination_path: str = Field(
        ..., description="Path where file/directory should be copied to"
    )

    @field_validator("source_path", "destination_path", mode="before")
    @classmethod
    def validate_paths(cls, path: str) -> str:
        return validate_non_empty_path(path)

    def display_header(self, interface: "SolveigInterface") -> None:
        """Display copy requirement header."""
        interface.display_comment(self.comment)
        abs_source = Filesystem.get_absolute_path(self.source_path)
        abs_dest = Filesystem.get_absolute_path(self.destination_path)
        path_info = format_path_info(
            path=self.source_path,
            abs_path=abs_source,
            is_dir=Filesystem._is_dir(abs_source),
            destination_path=self.destination_path,
            absolute_destination_path=abs_dest,
        )
        interface.show(path_info)

    def create_error_result(self, error_message: str, accepted: bool) -> "CopyResult":
        """Create CopyResult with error."""
        return CopyResult(
            requirement=self,
            accepted=accepted,
            error=error_message,
            source_path=Filesystem.get_absolute_path(self.source_path),
            destination_path=Filesystem.get_absolute_path(self.destination_path),
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of copy capability."""
        return "copy(source_path, destination_path): copies a file or directory"

    def _actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "CopyResult":
        # Pre-flight validation - use utils/file.py validation
        abs_source_path = Filesystem.get_absolute_path(self.source_path)
        abs_destination_path = Filesystem.get_absolute_path(self.destination_path)
        error: Exception | None = None

        try:
            Filesystem.validate_read_access(abs_source_path)
            Filesystem.validate_write_access(abs_destination_path)
        except FileExistsError as e:
            # Destination file already exists - print information, allow user to overwrite
            error = e
            interface.display_warning("Destination path already exists")

            destination_metadata = Filesystem.read_metadata(abs_destination_path)
            try:
                destination_listing = Filesystem.get_dir_listing(abs_destination_path)
            except NotADirectoryError:
                destination_listing = None
            interface.display_tree(
                metadata=destination_metadata,
                listing=destination_listing,
                title="Destination Metadata",
            )

        except Exception as e:
            interface.display_error(f"Skipping: {e}")
            return CopyResult(
                requirement=self,
                accepted=False,
                error=str(e),
                source_path=abs_source_path,
                destination_path=abs_destination_path,
            )

        source_metadata = Filesystem.read_metadata(abs_source_path)
        try:
            source_listing = Filesystem.get_dir_listing(abs_source_path)
        except NotADirectoryError:
            source_listing = None

        interface.display_tree(
            metadata=source_metadata, listing=source_listing, title="Source Metadata"
        )

        # Get user consent
        if interface.ask_yes_no(
            f"Allow copying '{abs_source_path}' to '{abs_destination_path}'? [y/N]: "
        ):
            try:
                # Perform the copy operation - use utils/file.py method
                Filesystem.copy(
                    abs_source_path,
                    abs_destination_path,
                    min_space_left=config.min_disk_space_left,
                )
                with interface.with_indent():
                    interface.display_success("Copied")
                return CopyResult(
                    requirement=self,
                    accepted=True,
                    source_path=abs_source_path,
                    destination_path=abs_destination_path,
                )
            except (PermissionError, OSError, FileExistsError) as e:
                interface.display_error(f"Found error when copying: {e}")
                return CopyResult(
                    requirement=self,
                    accepted=False,
                    error=str(e),
                    source_path=abs_source_path,
                    destination_path=abs_destination_path,
                )
        else:
            return CopyResult(
                requirement=self,
                accepted=False,
                source_path=abs_source_path,
                destination_path=abs_destination_path,
                error=str(
                    error
                ),  # allows us to return a "No" with the reason being that the file existed
            )
