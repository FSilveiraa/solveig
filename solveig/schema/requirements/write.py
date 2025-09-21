"""Write requirement - allows LLM to create/update files and directories."""

from typing import TYPE_CHECKING, Literal

from pydantic import Field, field_validator

from solveig.schema.requirements.base import (
    Requirement,
    format_path_info,
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

    def display_header(
        self, interface: "SolveigInterface", detailed: bool = False
    ) -> None:
        """Display write requirement header."""
        super().display_header(interface)
        abs_path = Filesystem.get_absolute_path(self.path)
        path_info = format_path_info(
            path=self.path, abs_path=abs_path, is_dir=self.is_directory
        )
        interface.display_text(path_info)
        if self.content and detailed:
            interface.display_text_block(self.content, title="Content")

    def create_error_result(self, error_message: str, accepted: bool) -> "WriteResult":
        """Create WriteResult with error."""
        return WriteResult(
            requirement=self,
            path=Filesystem.get_absolute_path(self.path),
            accepted=accepted,
            error=error_message,
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of write capability."""
        return "write(path, is_directory, content=null): creates a new file or directory, or updates an existing file. If it's a file, you may provide content to write."

    def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "WriteResult":
        abs_path = Filesystem.get_absolute_path(self.path)

        Filesystem.validate_write_access(
            path=abs_path,
            content=self.content,
            min_disk_size_left=config.min_disk_space_left,
        )
        # metadata = Filesystem.read_metadata(abs_path)

        already_exists = Filesystem.exists(abs_path)
        if already_exists:
            interface.display_warning("Overwriting existing file")
            file_content = Filesystem.read_file(abs_path)
            interface.display_text_block(
                (
                    str(file_content.content)
                    if file_content.encoding == "text"
                    else "( Binary Content )"
                ),
                title=str(abs_path),
            )

        auto_write = Filesystem.path_matches_patterns(
            abs_path, config.auto_allowed_paths
        )
        if auto_write:
            interface.display_text(
                f"{"Updating" if already_exists else "Creating"} {abs_path} since it matches config.auto_allowed_paths"
            )
        else:
            question = (
                f"Allow {'creating' if self.is_directory and not already_exists else 'updating'} "
                f"{'directory' if self.is_directory else 'file'}"
                f"{' and contents' if not self.is_directory else ''}? [y/N]: "
            )
            if not interface.ask_yes_no(question):
                return WriteResult(requirement=self, path=abs_path, accepted=False)

        try:
            # Perform the write operation - use utils/file.py methods
            if self.is_directory:
                Filesystem.create_directory(abs_path)
            else:
                Filesystem.write_file(abs_path, content=self.content or "")
            interface.display_success(f"{'Updated' if already_exists else 'Created'}")

            return WriteResult(requirement=self, path=abs_path, accepted=True)

        except Exception as e:
            interface.display_error(f"Found error when writing file: {e}")
            return WriteResult(
                requirement=self,
                path=abs_path,
                accepted=False,
                error=f"Encoding error: {e}",
            )
