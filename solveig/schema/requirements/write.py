"""Write requirement - allows LLM to create/update files and directories."""

from typing import TYPE_CHECKING, Literal

from pydantic import Field, field_validator

from solveig.schema.requirements.base import (
    Requirement,
    validate_non_empty_path,
)
from solveig.utils.file import Filesystem

if TYPE_CHECKING:
    from solveig.config import SolveigConfig
    from solveig.interface import SolveigInterface
    from solveig.schema.results import WriteResult
else:
    from solveig.schema.results import WriteResult


class WriteRequirement(Requirement):
    title: Literal["write"] = "write"
    path: str = Field(
        ...,
        description="File or directory path to create/update (supports ~ for home directory)",
    )
    is_directory: bool = Field(
        ..., description="If true, create a directory; if false, create a file"
    )
    content: str | None = Field(
        None, description="File content to write (only used when is_directory=false)"
    )

    @field_validator("path")
    @classmethod
    def path_not_empty(cls, path: str) -> str:
        return validate_non_empty_path(path)

    async def display_header(self, interface: "SolveigInterface") -> None:
        """Display write requirement header."""
        await super().display_header(interface)
        await interface.display_file_info(
            source_path=self.path,
            is_directory=self.is_directory,
            source_content=self.content,
            # show_overwrite_warning=False,
        )
        # abs_path = Filesystem.get_absolute_path(self.path)
        # path_info = format_path_info(
        #     path=self.path, abs_path=abs_path, is_dir=self.is_directory
        # )
        # await interface.display_text(path_info)
        # if self.content:
        #     if await Filesystem.exists(abs_path):
        #         file_content = await Filesystem.read_file(abs_path)
        #         await interface.display_diff(
        #             old_content=str(file_content.content), new_content=self.content
        #         )
        #         await interface.display_warning("Overwriting existing file")
        #     else:
        #         await interface.display_text_block(
        #             self.content, language=abs_path.suffix.lstrip("."), title="Content"
        #         )

    def create_error_result(self, error_message: str, accepted: bool) -> "WriteResult":
        """Create WriteResult with error."""
        return WriteResult(
            requirement=self,
            path=str(Filesystem.get_absolute_path(self.path)),
            accepted=accepted,
            error=error_message,
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of write capability."""
        return "write(comment, path, is_directory, content=null): creates a new file or directory, or updates an existing file. If it's a file, you may provide content to write."

    async def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "WriteResult":
        abs_path = Filesystem.get_absolute_path(self.path)

        await Filesystem.validate_write_access(
            path=abs_path,
            content=self.content,
            min_disk_size_left=config.min_disk_space_left,
        )

        already_exists = await Filesystem.exists(abs_path)

        auto_write = Filesystem.path_matches_patterns(
            abs_path, config.auto_allowed_paths
        )
        if auto_write:
            await interface.display_text(
                f"{"Updating" if already_exists else "Creating"} {abs_path} since it matches config.auto_allowed_paths"
            )
        else:
            question = (
                f"Allow {'creating' if not already_exists else 'updating'} "
                f"{'directory' if self.is_directory else 'file'}? [y/N]: "
            )
            if not await interface.ask_yes_no(question):
                return WriteResult(requirement=self, path=str(abs_path), accepted=False)

        try:
            # Perform the write operation - use utils/file.py methods
            if self.is_directory:
                await Filesystem.create_directory(abs_path)
            else:
                await Filesystem.write_file(abs_path, content=self.content or "")
            await interface.display_success(
                f"{'Updated' if already_exists else 'Created'}"
            )

            return WriteResult(requirement=self, path=str(abs_path), accepted=True)

        except Exception as e:
            await interface.display_error(f"Found error when writing file: {e}")
            return WriteResult(
                requirement=self,
                path=str(abs_path),
                accepted=False,
                error=f"Encoding error: {e}",
            )
