"""Write requirement - allows LLM to create/update files and directories."""

from typing import TYPE_CHECKING, Literal

from pydantic import Field, field_validator

from solveig.utils.file import Filesystem

from .base import Requirement, format_path_info, validate_non_empty_path

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

    def display_header(self, interface: "SolveigInterface") -> None:
        """Display write requirement header."""
        interface.display_comment(self.comment)
        abs_path = Filesystem.get_absolute_path(self.path)
        path_info = format_path_info(
            path=self.path, abs_path=abs_path, is_dir=self.is_directory
        )
        interface.show(path_info)
        if self.content:
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

    def _actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "WriteResult":
        abs_path = Filesystem.get_absolute_path(self.path)

        # Confirm if path exists and validate write access - use utils/file.py validation
        try:
            Filesystem.validate_write_access(
                path=abs_path,
                content=self.content,
                min_disk_size_left=config.min_disk_space_left,
            )
            metadata = Filesystem.read_metadata(abs_path)
            already_exists = True

            if already_exists:
                interface.display_warning("This file already exists")
                interface.display_tree(metadata, None)
        except FileNotFoundError:
            # File does not exist
            already_exists = False

        question = (
            f"Allow {'creating' if self.is_directory and not already_exists else 'updating'} "
            f"{'directory' if self.is_directory else 'file'}"
            f"{' and contents' if not self.is_directory else ''}? [y/N]: "
        )
        if interface.ask_yes_no(question):
            try:
                # Perform the write operation - use utils/file.py methods
                if self.is_directory:
                    Filesystem.create_directory(abs_path)
                else:
                    Filesystem.write_file(abs_path, content=self.content or "")
                with interface.with_indent():
                    interface.display_success(
                        f"{'Updated' if already_exists else 'Created'}"
                    )

                return WriteResult(requirement=self, path=abs_path, accepted=True)

            except Exception as e:
                interface.display_error(f"Found error when writing file: {e}")
                return WriteResult(
                    requirement=self,
                    path=abs_path,
                    accepted=False,
                    error=f"Encoding error: {e}",
                )
        else:
            return WriteResult(requirement=self, path=abs_path, accepted=False)
