"""Read requirement - allows LLM to read files and directories."""

from typing import TYPE_CHECKING, Literal

from pydantic import Field, field_validator

from solveig.utils.file import Filesystem

from .base import Requirement, format_path_info, validate_non_empty_path

if TYPE_CHECKING:
    from solveig.config import SolveigConfig
    from solveig.interface import SolveigInterface
    from solveig.schema.results import ReadResult
else:
    from solveig.schema.results import ReadResult


class ReadRequirement(Requirement):
    title: Literal["read"] = "read"
    path: str = Field(
        ...,
        description="File or directory path to read (supports ~ for home directory)",
    )
    metadata_only: bool = Field(
        ...,
        description="If true, read only file/directory metadata; if false, read full contents",
    )

    @field_validator("path")
    @classmethod
    def path_not_empty(cls, path: str) -> str:
        return validate_non_empty_path(path)

    def display_header(
        self, interface: "SolveigInterface", detailed: bool = False
    ) -> None:
        """Display read requirement header."""
        super().display_header(interface)
        abs_path = Filesystem.get_absolute_path(self.path)
        path_info = format_path_info(
            path=self.path, abs_path=abs_path, is_dir=Filesystem.is_dir(abs_path)
        )
        interface.display_text(path_info)

    def create_error_result(self, error_message: str, accepted: bool) -> "ReadResult":
        """Create ReadResult with error."""
        return ReadResult(
            requirement=self,
            path=Filesystem.get_absolute_path(self.path),
            accepted=accepted,
            error=error_message,
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of read capability."""
        return "read(path, metadata_only): reads a file or directory. If it's a file, you can choose to read the metadata only, or the contents+metadata."

    def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "ReadResult":
        abs_path = Filesystem.get_absolute_path(self.path)

        # Pre-flight validation - use utils/file.py validation
        try:
            Filesystem.validate_read_access(abs_path)
        except (FileNotFoundError, PermissionError, IsADirectoryError) as e:
            interface.display_error(f"Cannot access {abs_path}: {e}")
            return ReadResult(
                requirement=self, path=abs_path, accepted=False, error=str(e)
            )

        auto_read = Filesystem.path_matches_patterns(
            abs_path, config.auto_allowed_paths
        )
        if auto_read:
            interface.display_text(
                f"Reading {abs_path} since it matches config.allow_allowed_paths"
            )
        metadata = Filesystem.read_metadata(abs_path)
        interface.display_tree(
            metadata, title=f"Metadata: {abs_path}", display_metadata=True
        )
        content = None

        if (
            not metadata.is_directory
            and not self.metadata_only
            and (
                auto_read
                or interface.ask_yes_no("Allow reading file contents? [y/N]: ")
            )
        ):
            try:
                read_result = Filesystem.read_file(abs_path)
                content = read_result.content
                metadata.encoding = read_result.encoding
            except (PermissionError, OSError, UnicodeDecodeError) as e:
                interface.display_error(f"Failed to read file contents: {e}")
                return ReadResult(
                    requirement=self, path=abs_path, accepted=False, error=str(e)
                )

            content_output = (
                "(Base64)" if metadata.encoding.lower() == "base64" else str(content)
            )
            interface.display_text_block(content_output, title=f"Content: {abs_path}")

        if config.auto_send:
            interface.display_text(
                f"Sending {"content" if content else "metadata"} since config.auto_send=True"
            )
        if (
            config.auto_send
            # if we can automatically read any file within a pattern,
            # it makes sense to also automatically send back the contents
            or interface.ask_yes_no(
                f"Allow sending {'file content and ' if content else ''}metadata? [y/N]: "
            )
        ):
            return ReadResult(
                requirement=self,
                path=abs_path,
                accepted=True,
                metadata=metadata,
                content=str(content) if content is not None else None,
            )
        else:
            return ReadResult(requirement=self, path=abs_path, accepted=False)
