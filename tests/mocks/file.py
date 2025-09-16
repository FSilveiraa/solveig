"""
Mock file system for testing file operations without touching real files.
Only overrides the essential MockFileSystem low-level methods.
"""

from contextlib import contextmanager
from copy import copy
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from solveig.utils.file import Filesystem, Metadata

DEFAULT_METADATA = Metadata(
    owner_name="test-user",
    group_name="test-user",
    path=None,
    size=0,
    modified_time=0,
    is_directory=True,
    is_readable=True,
    is_writable=True,
    encoding=None,
    listing=None,
)


def create_metadata(path: Path, modified_time=-1, **kwargs) -> Metadata:
    if modified_time is None or modified_time < 0:
        modified_time = int(datetime.now().timestamp())
    return replace(DEFAULT_METADATA, path=path, modified_time=modified_time, **kwargs)


@dataclass
class MockFileDir:
    metadata: Metadata
    content: str | None = None

    @staticmethod
    def create_dir(path: Path, **kwargs) -> "MockFileDir":
        listing = kwargs.pop("listing", {})
        return MockFileDir(
            metadata=create_metadata(
                path=path, is_directory=True, listing=listing, size=4096, **kwargs
            )
        )

    @staticmethod
    def create_file(
        abs_path: Path, content: str | None = None, **kwargs
    ) -> "MockFileDir":
        size = kwargs.pop("size", len(content.encode("utf-8")) if content else 0)
        return MockFileDir(
            metadata=create_metadata(
                path=abs_path, is_directory=False, size=size, **kwargs
            ),
            content=content,
        )


class MockFilesystem(Filesystem):
    def __init__(self, total_size=1000000000):  # 1GB
        # Store (content, metadata) tuples - single source of truth
        self._entries: dict[Path, MockFileDir] = {}
        self.mocks = (
            SimpleNamespace()
        )  # Store references to mock objects for direct access
        self.total_size = total_size

    def reset(self):
        """Reset the mock file system to default test state."""
        self._entries.clear()
        self.create_directory(Path("/"))
        # Add some default test files that tests expect
        self.write_file("/test/dir1/dir2/file.txt", "test content")
        self.write_file("/test/file.txt", "test content")
        self.write_file("/test/source.txt", "source content")
        self.write_file("/test/original.txt", "original content")
        self.write_file("/test/unwanted.txt", "unwanted content")
        self.create_directory("/test/dir")
        self.create_directory("/test/dir/subdir")
        self.write_file("/test/dir/nested.txt")

        self.create_directory("/test/dir2")
        self.create_directory("test/dir2/sub-d1/sub-d2")
        self.write_file("/test/dir2/sub-d1/sub-d2/f4", "This is f4")
        self.write_file("/test/dir2/sub-d1/sub-d2/f4", "And this is f5")
        self.write_file("/test/dir2/sub-d1/sub-d2/f4", "F6 here")
        self.write_file("/test/dir2/sub-d1/sub-d3/f3", "One level down")
        self.write_file("/test/dir2/f1")

    def _update_directory_listings(self) -> None:
        """Update all directory listings to reflect current filesystem state."""
        # Clear all listings first
        for entry in self._entries.values():
            if entry.metadata.is_directory:
                entry.metadata.listing.clear()

        # Rebuild all listings
        for path, entry in self._entries.items():
            if path != path.parent and path.parent in self._entries:
                parent_entry = self._entries[path.parent]
                assert parent_entry.metadata.is_directory
                parent_entry.metadata.listing[path] = entry.metadata

    # ====  OVERRIDES  ====

    def _mock_exists(self, abs_path: Path) -> bool:
        return abs_path in self._entries

    def _mock_is_dir(self, abs_path: Path) -> bool:
        entry = self._entries.get(abs_path, None)
        return entry.metadata.is_directory if entry else False

    # TODO: find a way to account for descending level
    def _mock_read_metadata(self, abs_path: Path, descend_level=1) -> Metadata:
        try:
            return self._entries[abs_path].metadata
        except KeyError as e:
            raise FileNotFoundError(abs_path) from e

    def _mock_get_listing(self, abs_path: Path) -> list[Path]:
        return sorted(
            path for path, file in self._entries.items() if path.parent == abs_path
        )

    def _mock_read_text(self, abs_path: Path) -> str:
        return self._entries[abs_path].content

    def _mock_read_bytes(self, abs_path: Path) -> bytes:
        return self._entries[abs_path].content.encode("utf-8")

    def _mock_create_directory(self, abs_path: Path) -> None:
        self._entries[abs_path] = MockFileDir.create_dir(abs_path)
        self._update_directory_listings()

    def _mock_write_text(
        self, abs_path: Path, content: str = "", encoding="utf-8"
    ) -> None:
        self._entries[abs_path] = MockFileDir.create_file(
            abs_path, content, encoding=encoding
        )
        self._update_directory_listings()

    def _mock_append_text(
        self, abs_path: Path, content: str = "", encoding="utf-8"
    ) -> None:
        entry = self._entries[abs_path]
        entry.content = entry.content + content
        entry.metadata.modified_time = int(datetime.now().timestamp())
        entry.metadata.size = len(content.encode("utf-8"))

    def _mock_copy_file(self, abs_src_path: Path, abs_dest_path: Path) -> None:
        self._entries[abs_dest_path] = copy(self._entries[abs_src_path])

    def _mock_copy_dir(self, src_path: Path, dest_path: Path) -> None:
        self._mock_copy_file(src_path, dest_path)

    def _mock_move(self, src_path: Path, dest_path: Path) -> None:
        self._mock_copy_file(src_path, dest_path)
        del self._entries[src_path]

    # def _is_readable(abs_path: Path) -> bool:
    #     return os.access(abs_path, os.R_OK)
    #
    # @staticmethod
    # def _is_writable(abs_path: Path) -> bool:
    #     return os.access(abs_path, os.W_OK)

    def _mock_get_free_space(self, abs_path: Path) -> int:
        return self.total_size - sum(
            file.metadata.size for file in self._entries.values()
        )

    def _mock_delete_file(self, abs_path: Path) -> None:
        del self._entries[abs_path]

    def _mock_delete_dir(self, abs_path: Path) -> None:
        self._mock_delete_file(abs_path)

    def _mock_is_text_file(self, abs_path: Path) -> bool:
        return True

    @contextmanager
    def patch_all_file_operations(self):
        """Context manager that patches all file operations to use this mock filesystem."""
        with (
            patch.object(
                Filesystem, "exists", MagicMock(side_effect=self._mock_exists)
            ) as patch_exists,
            patch.object(
                Filesystem, "is_dir", MagicMock(side_effect=self._mock_is_dir)
            ) as patch_is_dir,
            patch.object(
                Filesystem,
                "read_metadata",
                MagicMock(side_effect=self._mock_read_metadata),
            ) as patch_read_metadata,
            patch.object(
                Filesystem,
                "_get_listing",
                MagicMock(side_effect=self._mock_get_listing),
            ) as patch_get_listing,
            patch.object(
                Filesystem, "_read_text", MagicMock(side_effect=self._mock_read_text)
            ) as patch_read_text,
            patch.object(
                Filesystem, "_read_bytes", MagicMock(side_effect=self._mock_read_bytes)
            ) as patch_read_bytes,
            patch.object(
                Filesystem,
                "_create_directory",
                MagicMock(side_effect=self._mock_create_directory),
            ) as patch_create_directory,
            patch.object(
                Filesystem, "_write_text", MagicMock(side_effect=self._mock_write_text)
            ) as patch_write_text,
            patch.object(
                Filesystem,
                "_append_text",
                MagicMock(side_effect=self._mock_append_text),
            ) as patch_append_text,
            patch.object(
                Filesystem, "_copy_file", MagicMock(side_effect=self._mock_copy_file)
            ) as patch_copy_file,
            patch.object(
                Filesystem, "_copy_dir", MagicMock(side_effect=self._mock_copy_dir)
            ) as patch_copy_dir,
            patch.object(
                Filesystem, "_move", MagicMock(side_effect=self._mock_move)
            ) as patch_move,
            patch.object(
                Filesystem,
                "_get_free_space",
                MagicMock(side_effect=self._mock_get_free_space),
            ) as patch_get_free_space,
            patch.object(
                Filesystem,
                "_delete_file",
                MagicMock(side_effect=self._mock_delete_file),
            ) as patch_delete_file,
            patch.object(
                Filesystem, "_delete_dir", MagicMock(side_effect=self._mock_delete_dir)
            ) as patch_delete_dir,
            patch.object(
                Filesystem,
                "_is_text_file",
                MagicMock(side_effect=self._mock_is_text_file),
            ) as patch_is_text_file,
            # ! Important: even though DEFAULT_CONFIG_PATH is defined in config.py,
            # we have to patch where it's used which is on scripts/init.py
            patch(
                "scripts.init.DEFAULT_CONFIG_PATH",
                Path("/home/_test_user_/.config.json"),
            ) as patch_default_config,
            patch(
                "scripts.init.DEFAULT_BASHRC_PATH", Path("/home/_test_user_/.bashrc")
            ) as patch_default_bashrc,
        ):
            # Reset to clean state
            self.reset()

            # Store mock references in a namespace for direct access in tests
            self.mocks = SimpleNamespace(
                exists=patch_exists,
                is_dir=patch_is_dir,
                read_metadata=patch_read_metadata,
                get_listing=patch_get_listing,
                read_text=patch_read_text,
                read_bytes=patch_read_bytes,
                create_directory=patch_create_directory,
                write_text=patch_write_text,
                append_text=patch_append_text,
                copy_file=patch_copy_file,
                copy_dir=patch_copy_dir,
                move=patch_move,
                get_free_space=patch_get_free_space,
                delete_file=patch_delete_file,
                delete_dir=patch_delete_dir,
                is_text_file=patch_is_text_file,
                default_bashrc_path=patch_default_bashrc,
                default_config_path=patch_default_config,
            )

            yield self


mock_fs = MockFilesystem()
