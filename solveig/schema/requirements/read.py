"""Read requirement - allows LLM to read files and directories."""

from typing import Literal

from pydantic import Field, field_validator

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.results import ReadResult
from solveig.utils.file import Filesystem

from .base import Requirement, validate_non_empty_path


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

    async def display_header(self, interface: "SolveigInterface") -> None:
        """Display read requirement header."""
        await super().display_header(interface)
        await interface.display_file_info(source_path=self.path)

        metadata = await Filesystem.read_metadata(
            Filesystem.get_absolute_path(self.path)
        )

        # Display the dir listing for directories (1-depth tree)
        if metadata.is_directory:
            await interface.display_tree(metadata=metadata)
        # The metadata vs content distinction only makes sense for files
        else:
            await interface.display_text(
                f"{'' if self.metadata_only else 'content and '}metadata",
                prefix="Requesting:",
            )

    def create_error_result(self, error_message: str, accepted: bool) -> "ReadResult":
        """Create ReadResult with error."""
        return ReadResult(
            requirement=self,
            path=str(Filesystem.get_absolute_path(self.path)),
            accepted=accepted,
            error=error_message,
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of read capability."""
        return "read(comment, path, metadata_only): reads a file or directory. If it's a file, you can choose to read the metadata only, or the contents+metadata."

    async def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "ReadResult":
        abs_path = Filesystem.get_absolute_path(self.path)

        # Read access validation
        try:
            await Filesystem.validate_read_access(abs_path)
        except (FileNotFoundError, PermissionError, IsADirectoryError) as e:
            await interface.display_error(f"Cannot access {str(abs_path)}: {e}")
            return ReadResult(
                requirement=self, path=str(abs_path), accepted=False, error=str(e)
            )

        path_matches = Filesystem.path_matches_patterns(
            abs_path, config.auto_allowed_paths
        )
        metadata = await Filesystem.read_metadata(abs_path)

        # directory or file metadata only
        if metadata.is_directory or self.metadata_only:
            if path_matches:
                send_metadata = True
                await interface.display_info(
                    "Sending metadata since it matches config.allow_allowed_paths"
                )
            else:
                send_metadata = (
                    await interface.ask_choice("Allow sending metadata?", ["Yes", "No"])
                    == 0
                )
            return ReadResult(
                requirement=self,
                metadata=metadata if send_metadata else None,
                path=str(abs_path),
                accepted=send_metadata,
            )

        # file content
        else:
            accepted = False
            file_content = None

            if path_matches:
                choice_read_file = 0
                await interface.display_text(
                    "Reading file and sending content since it matches config.allow_allowed_paths"
                )
            else:
                choice_read_file = await interface.ask_choice(
                    "Allow reading file?",
                    [
                        "Read and send content and metadata",
                        "Read and inspect content first",
                        "Don't read and only send metadata",
                        "Don't read or send anything",
                    ],
                )

            # User chose to read the file
            if choice_read_file in {0, 1}:
                # read file
                try:
                    read_result = await Filesystem.read_file(abs_path)
                    file_content = read_result.content
                    metadata.encoding = read_result.encoding
                except (PermissionError, OSError, UnicodeDecodeError) as e:
                    await interface.display_error(f"Failed to read file content: {e}")
                    return ReadResult(
                        requirement=self,
                        path=str(abs_path),
                        accepted=False,
                        error=str(e),
                    )

                # display content
                content_output = (
                    "(Base64)"
                    if metadata.encoding.lower() == "base64"
                    else str(file_content)
                    if file_content
                    else ""
                )
                await interface.display_text_block(
                    content_output,
                    title=f"Content: {abs_path}",
                    language=abs_path.suffix,
                )

                if file_content:
                    if choice_read_file == 0:
                        accepted = True
                    # If the user previously chose to inspect the output first, confirm again
                    else:
                        choice_send_file = await interface.ask_choice(
                            "Send file content?",
                            [
                                "Send content and metadata",
                                "Send metadata only",
                                "Don't send anything",
                            ],
                        )
                        if choice_send_file == 0:
                            accepted = True
                        elif choice_send_file == 1:
                            file_content = "<hidden>"
                        elif choice_send_file == 2:
                            file_content = "<hidden>"
                            metadata = None

            # "Don't read and only send metadata" - don't do anything
            # "Don't read or send anything" - clear metadata
            elif choice_read_file == 3:
                metadata = None

            return ReadResult(
                requirement=self,
                metadata=metadata,
                content=file_content if file_content else "",
                path=str(abs_path),
                accepted=accepted,
            )
