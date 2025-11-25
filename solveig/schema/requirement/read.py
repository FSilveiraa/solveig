"""Read requirement - allows LLM to read files and directories."""

from typing import Literal

from pydantic import Field, field_validator

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.result import ReadResult
from solveig.utils.file import Filesystem, Metadata

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

        try:
            await Filesystem.validate_read_access(abs_path)
        except (FileNotFoundError, PermissionError, IsADirectoryError) as e:
            await interface.display_error(f"Cannot access {str(abs_path)}: {e}")
            return self.create_error_result(str(e), accepted=False)

        path_matches = Filesystem.path_matches_patterns(
            abs_path, config.auto_allowed_paths
        )

        metadata: Metadata | None = await Filesystem.read_metadata(abs_path)
        assert metadata is not None

        # Case 1: Directories or metadata-only requests
        if metadata.is_directory or self.metadata_only:
            send_metadata = False
            if path_matches:
                await interface.display_info(
                    "Sending metadata since path is auto-allowed."
                )
                send_metadata = True
            else:
                send_metadata = (
                    await interface.ask_choice(
                        "Send metadata to assistant?", ["Yes", "No"]
                    )
                    == 0
                )

            return ReadResult(
                requirement=self,
                metadata=metadata if send_metadata else None,
                path=str(abs_path),
                accepted=send_metadata,
            )

        # Case 2: File content requests
        else:
            accepted = False
            content: str | bytes | None = None

            if path_matches:
                await interface.display_info(
                    "Reading and sending file since path is auto-allowed."
                )
                choice = 0  # Corresponds to "Read and send"
            else:
                choice = await interface.ask_choice(
                    "Allow reading file?",
                    [
                        "Read and send content and metadata",
                        "Read and inspect content first",
                        "Send metadata only",
                        "Don't send anything",
                    ],
                )

            if choice in {0, 1}:
                read_result = await Filesystem.read_file(abs_path)
                content = read_result.content
                metadata.encoding = read_result.encoding
                await interface.display_text_block(
                    content if read_result.encoding == "text" else "(binary content)",
                    title=f"Content: {abs_path}",
                    language=abs_path.suffix,
                )

                # 0: Read and send
                if choice == 0:
                    accepted = True
                # 1: Read and inspect
                elif choice == 1:
                    try:
                        send_choice = await interface.ask_choice(
                            "Send file content?",
                            [
                                "Send content and metadata",
                                "Send metadata only",
                                "Don't send anything",
                            ],
                        )
                        if send_choice == 0:
                            accepted = True
                        elif send_choice == 1:
                            accepted = False  # Didn't get content
                            content = None
                        else:  # Don't send anything
                            accepted = False
                            content = None
                            metadata = None

                    except (PermissionError, OSError, UnicodeDecodeError) as e:
                        await interface.display_error(
                            f"Failed to read file content: {e}"
                        )
                        return self.create_error_result(str(e), accepted=False)
            # 2: Send metadata only
            elif choice == 2:
                accepted = False  # Didn't get content
                content = None
            # 3: Don't send anything
            else:
                accepted = False
                content = None
                metadata = None

            return ReadResult(
                requirement=self,
                metadata=metadata,
                content=content,
                path=str(abs_path),
                accepted=accepted,
            )
