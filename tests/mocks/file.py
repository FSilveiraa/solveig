"""
Streamlined mock file system for testing file operations without touching real files.
Only contains the essential MockFileSystem class and integrated mock methods.
"""

import datetime
from contextlib import contextmanager
from copy import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from solveig.utils.file import Filesystem, Metadata


class MockFilesystem(Filesystem):
    def __init__(self, total_size=1000000000):  # 1GB
        # Store (content, metadata) tuples - single source of truth
        self._entries: dict[Path, tuple[str, Metadata]] = {}
        self.mocks = SimpleNamespace()  # Store references to mock objects for direct access
        self.total_size = total_size

    def reset(self):
        """Reset the mock file system to default test state."""
        self._entries.clear()
        self._create_directory(Path("/"))
        # Add some default test files that tests expect
        self.write_file("/test/dir1/dir2/file.txt", "test content")
        self.write_file("/test/file.txt", "test content")
        self.write_file("/test/source.txt", "source content")
        self.write_file("/test/original.txt", "original content")
        self.write_file("/test/unwanted.txt", "unwanted content")
        self.create_directory("/test/dir")
        self.create_directory("/test/dir/subdir")
        self.write_file("/test/dir/nested.txt")

    def create_directory(self, path: str | Path) -> None:
        """Helper method to create a directory and ensure parent directories exist."""
        abs_path = Path(path).resolve()
        
        # Ensure parent directories exist
        for parent in reversed(abs_path.parents):
            if parent not in self._entries:
                self._create_directory(parent)
        
        self._create_directory(abs_path)

    def write_file(self, path: str | Path, content: str = "") -> None:
        """Helper method to write a file and ensure parent directories exist."""
        abs_path = Path(path).resolve()
        
        # Ensure parent directories exist
        for parent in reversed(abs_path.parents):
            if parent not in self._entries:
                self._create_directory(parent)
        
        self._write_text(abs_path, content)

    def _create_directory(self, abs_path: Path) -> None:
        """Create directory entry with proper metadata."""
        metadata = Metadata(
            path=abs_path,
            size=4096,
            modified_time=datetime.datetime.now().isoformat(),
            is_directory=True,
            owner_name="test-user",
            group_name="test-group",
            is_readable=True,
            is_writable=True,
            listing={}  # Will be populated by _update_directory_listings
        )
        self._entries[abs_path] = ("", metadata)  # Directories have no content
        self._update_directory_listings()

    def _write_text(self, abs_path: Path, content: str = "", encoding = "utf-8") -> None:
        """Write file entry with proper metadata."""
        metadata = Metadata(
            path=abs_path,
            size=len(content.encode("utf-8")),
            modified_time=datetime.datetime.now().isoformat(),
            is_directory=False,
            owner_name="test-user",
            group_name="test-group",
            is_readable=True,
            is_writable=True
        )
        self._entries[abs_path] = (content, metadata)
        self._update_directory_listings()

    def _update_directory_listings(self) -> None:
        """Update all directory listings to reflect current filesystem state."""
        # Clear all listings first
        for content, metadata in self._entries.values():
            if metadata.is_directory:
                metadata.listing.clear()
        
        # Rebuild all listings
        for path, (content, metadata) in self._entries.items():
            parent = path.parent
            if parent in self._entries:
                parent_content, parent_metadata = self._entries[parent]
                if parent_metadata.is_directory:
                    parent_metadata.listing[path] = metadata

    # Core mock methods that patch Filesystem static methods
    def _mock_exists(self, abs_path: str | Path) -> bool:
        return Path(abs_path) in self._entries

    def _mock_is_dir(self, abs_path: Path) -> bool:
        entry = self._entries.get(Path(abs_path))
        return entry is not None and entry[1].is_directory

    def _mock_read_metadata(self, abs_path: Path, descend_level=0) -> Metadata:
        try:
            content, metadata = self._entries[Path(abs_path)]
            return metadata
        except KeyError as e:
            raise FileNotFoundError(abs_path) from e

    def _mock_get_listing(self, abs_path: Path) -> list[Path]:
        return sorted(
            path for path in self._entries.keys() if path.parent == abs_path
        )

    def _mock_read_text(self, abs_path: Path) -> str:
        content, metadata = self._entries[Path(abs_path)]
        if metadata.is_directory:
            raise IsADirectoryError(abs_path)
        return content

    def _mock_read_bytes(self, abs_path: Path) -> bytes:
        return self._mock_read_text(abs_path).encode("utf-8")

    def _mock_append_text(self, abs_path: Path, content: str = "", encoding="utf-8") -> None:
        existing_content, metadata = self._entries.get(Path(abs_path), ("", None))
        self._write_text(abs_path, existing_content + content)

    def _mock_copy_file(self, abs_src_path: Path, abs_dest_path: Path) -> None:
        src_content, src_metadata = self._entries[Path(abs_src_path)]
        # Create copy with new path
        new_metadata = Metadata(
            path=abs_dest_path,
            size=src_metadata.size,
            modified_time=datetime.datetime.now().isoformat(),
            is_directory=src_metadata.is_directory,
            owner_name=src_metadata.owner_name,
            group_name=src_metadata.group_name,
            is_readable=src_metadata.is_readable,
            is_writable=src_metadata.is_writable,
            listing=copy(src_metadata.listing) if src_metadata.is_directory else None
        )
        self._entries[abs_dest_path] = (src_content, new_metadata)
        self._update_directory_listings()

    def _mock_copy_dir(self, src_path: Path, dest_path: Path) -> None:
        self._mock_copy_file(src_path, dest_path)

    def _mock_move(self, src_path: Path, dest_path: Path) -> None:
        self._mock_copy_file(src_path, dest_path)
        del self._entries[Path(src_path)]
        self._update_directory_listings()

    def _mock_get_free_space(self, abs_path: Path) -> int:
        used_space = sum(metadata.size for content, metadata in self._entries.values())
        return self.total_size - used_space

    def _mock_delete_file(self, abs_path: Path) -> None:
        del self._entries[Path(abs_path)]
        self._update_directory_listings()

    def _mock_delete_dir(self, abs_path: Path) -> None:
        # Remove directory and all children
        abs_path = Path(abs_path)
        to_delete = [path for path in self._entries.keys() 
                    if path == abs_path or path.is_relative_to(abs_path)]
        for path in to_delete:
            del self._entries[path]
        self._update_directory_listings()

    def _mock_is_text_file(self, abs_path: Path) -> bool:
        return True

    @contextmanager
    def patch_all_file_operations(self):
        """Context manager that patches all file operations to use this mock filesystem."""
        with (
            patch.object(
                Filesystem, "_exists", MagicMock(side_effect=self._mock_exists)
            ) as patch_exists,
            patch.object(
                Filesystem, "_is_dir", MagicMock(side_effect=self._mock_is_dir)
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
                MagicMock(side_effect=self._create_directory),
            ) as patch_create_directory,
            patch.object(
                Filesystem, "_write_text", MagicMock(side_effect=self._write_text)
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
            patch(
                "solveig.config.DEFAULT_CONFIG_PATH",
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
                default_bashrc=patch_default_bashrc,
                default_config=patch_default_config,
            )

            yield self


mock_fs = MockFilesystem()