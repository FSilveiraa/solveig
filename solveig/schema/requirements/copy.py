"""Copy requirement - allows LLM to copy files and directories."""

from typing import TYPE_CHECKING, Literal

from pydantic import Field, field_validator

from solveig.utils.file import Filesystem

from .base import Requirement, validate_non_empty_path

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

    async def display_header(self, interface: "SolveigInterface") -> None:
        """Display copy requirement header."""
        await super().display_header(interface)
        await interface.display_file_info(
            source_path=self.source_path,
            destination_path=self.destination_path,
        )

        # abs_source = Filesystem.get_absolute_path(self.source_path)
        # abs_dest = Filesystem.get_absolute_path(self.destination_path)
        # is_dir = await Filesystem.is_dir(abs_source)
        # path_info = format_path_info(
        #     path=self.source_path,
        #     abs_path=abs_source,
        #     is_dir=is_dir,
        #     destination_path=self.destination_path,
        #     absolute_destination_path=abs_dest,
        # )
        # await interface.display_text(path_info)
        # if await Filesystem.exists(abs_dest) and await Filesystem.exists(abs_source):
        #     old = await Filesystem.read_file(abs_dest)
        #     new = await Filesystem.read_file(abs_source)
        #     await interface.display_diff(
        #         old_content=str(old.content), new_content=str(new.content)
        #     )
        #     await interface.display_warning("Overwriting existing file")

    def create_error_result(self, error_message: str, accepted: bool) -> "CopyResult":
        """Create CopyResult with error."""
        return CopyResult(
            requirement=self,
            accepted=accepted,
            error=error_message,
            source_path=str(Filesystem.get_absolute_path(self.source_path)),
            destination_path=str(Filesystem.get_absolute_path(self.destination_path)),
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of copy capability."""
        return (
            "copy(comment, source_path, destination_path): copies a file or directory"
        )

    async def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "CopyResult":
        # Pre-flight validation - use utils/file.py validation
        abs_source_path = Filesystem.get_absolute_path(self.source_path)
        abs_destination_path = Filesystem.get_absolute_path(self.destination_path)
        error: Exception | None = None

        try:
            await Filesystem.validate_read_access(abs_source_path)
            await Filesystem.validate_write_access(abs_destination_path)
        except Exception as e:
            await interface.display_error(f"Skipping: {e}")
            return CopyResult(
                requirement=self,
                accepted=False,
                error=str(e),
                source_path=str(abs_source_path),
                destination_path=str(abs_destination_path),
            )

        # Get user consent
        if (
            Filesystem.path_matches_patterns(abs_source_path, config.auto_allowed_paths)
            and Filesystem.path_matches_patterns(
                abs_destination_path, config.auto_allowed_paths
            )
        ) or await interface.ask_yes_no(
            f"Allow copying '{abs_source_path}' to '{abs_destination_path}'? [y/N]: "
        ):
            try:
                # Perform the copy operation - use utils/file.py method
                await Filesystem.copy(
                    abs_source_path,
                    abs_destination_path,
                    min_space_left=config.min_disk_space_left,
                )
                await interface.display_success("Copied")
                return CopyResult(
                    requirement=self,
                    accepted=True,
                    source_path=str(abs_source_path),
                    destination_path=str(abs_destination_path),
                )
            except (PermissionError, OSError, FileExistsError) as e:
                await interface.display_error(f"Found error when copying: {e}")
                return CopyResult(
                    requirement=self,
                    accepted=False,
                    error=str(e),
                    source_path=str(abs_source_path),
                    destination_path=str(abs_destination_path),
                )
        else:
            return CopyResult(
                requirement=self,
                accepted=False,
                source_path=str(abs_source_path),
                destination_path=str(abs_destination_path),
                error=str(
                    error
                ),  # allows us to return a "No" with the reason being that the file existed
            )
