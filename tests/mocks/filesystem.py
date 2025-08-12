"""
Streamlined mock file system for testing file operations without touching real files.
Only contains the essential MockFileSystem class and integrated mock methods.
"""
import datetime
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from copy import copy

from solveig.utils.filesystem import Filesystem, Metadata


class MockFile:
    def __init__(self, path: str | Path, content: str = "", metadata: Metadata | None = None, **metadata_kwargs) -> None:
        # super().__init__(path=MockFileSystem._abs_path(path), metadata=metadata)
        self.content = content
        self.metadata = metadata or Metadata(**{
            "path": path,
            "size": len(content.encode("utf-8")),
            "modified_time": str(datetime.datetime.now().isoformat()),
            "is_directory": False,
            "owner_name": "test-user",
            "group_name": "test-group",
            "is_readable": True,
            "is_writable": True,
            **metadata_kwargs
        })


class MockDir:
    def __init__(self, path: str | Path, metadata: Metadata | None = None, **metadata_kwargs) -> None:
        self.metadata = metadata or Metadata(**{
            "path": path,
            "size": 4096,
            "modified_time": str(datetime.datetime.now().isoformat()),
            "is_directory": True,
            "owner_name": "test-user",
            "group_name": "test-group",
            "is_readable": True,
            "is_writable": True,
            **metadata_kwargs
        })


class MockFilesystem(Filesystem):
    def __init__(self, total_size = 1000000000 ): # 1GB
        self._paths: dict[Path, MockDir | MockFile] = {}  # path -> {"content": str, "is_directory": bool, "metadata": dict, "listing": list}
        # self.directories: dict[Path, ]
        self.mocks = SimpleNamespace()  # Store references to mock objects for direct access
        self.total_size = total_size

    def reset(self):
        """Reset the mock file system to default test state."""
        self._paths.clear()
        self._create_directory(Path("/"))
        # Add parent directories first
        # self.add_directory(MockFileDir("/test", True))
        # Add some default test files that tests expect
        self.write_file("/test/dir1/dir2/file.txt", "test content")
        self.write_file("/test/file.txt", "test content")
        self.write_file("/test/source.txt", "source content")
        self.write_file("/test/original.txt", "original content")
        self.write_file("/test/unwanted.txt", "unwanted content")
        self.create_directory("/test/dir")
        self.create_directory("/test/dir/subdir")
        self.write_file("/test/dir/nested.txt")


    """
    Core functions
    
    Because these are static they have a fundamentally different signature from the real methods
    and all need to be renamed: _exists(abs_path) != _mock_exists(self, abs_path)
    otherwise if they have the same name we get this absurd error:
    >       if cls._exists(abs_path) and cls._is_dir(abs_path):
    E       TypeError: MockFilesystem._exists() missing 1 required positional argument: 'abs_path'
    """

    def _mock_exists(self, abs_path: str | Path) -> bool:
        return abs_path in self._paths

    def _mock_is_dir(self, abs_path: Path) -> bool:
        return isinstance(self._paths.get(abs_path, None), MockDir)

    def _mock_read_metadata(self, abs_path: Path) -> Metadata:
        try:
            return self._paths[abs_path].metadata
        except KeyError as e:
            raise FileNotFoundError(abs_path) from e

    def _mock_get_listing(self, abs_path: Path) -> list[Path]:
        return sorted(path for path, file in self._paths.items() if path.parent == abs_path)

    def _mock_read_text(self, abs_path: Path) -> str:
        return self._paths[abs_path].content

    def _mock_read_bytes(self, abs_path: Path) -> bytes:
        return self._paths[abs_path].content.encode("utf-8")

    def _mock_create_directory(self, abs_path: Path) -> None:
        self._paths[abs_path] = MockDir(path=abs_path)

    def _mock_write_text(self, abs_path: Path, content: str = "", encoding = "utf-8") -> None:
        self._paths.setdefault(abs_path, MockFile(path=abs_path, content="")).content = content

    def _mock_append_text(self, abs_path: Path, content: str = "", encoding = "utf-8") -> None:
        self._paths[abs_path].content += content

    def _mock_copy_file(self, abs_src_path: Path, abs_dest_path: Path) -> None:
        self._paths[abs_dest_path] = copy(self._paths[abs_src_path])

    def _mock_copy_dir(self, src_path: Path, dest_path: Path) -> None:
        self._mock_copy_file(src_path, dest_path)

    def _mock_move(self, src_path: Path, dest_path: Path) -> None:
        self._mock_copy_file(src_path, dest_path)
        del self._paths[src_path]

    # def _is_readable(abs_path: Path) -> bool:
    #     return os.access(abs_path, os.R_OK)
    #
    # @staticmethod
    # def _is_writable(abs_path: Path) -> bool:
    #     return os.access(abs_path, os.W_OK)

    def _mock_get_free_space(self, abs_path: Path) -> int:
        return self.total_size - sum(file.metadata.size for file in self._paths.values())

    def _mock_delete_file(self, abs_path: Path) -> None:
        del self._paths[abs_path]

    def _mock_delete_dir(self, abs_path: Path) -> None:
        self._mock_delete_file(abs_path)

    def _mock_is_text_file(self, abs_path: Path) -> bool:
        return True

    @contextmanager
    def patch_all_file_operations(self):
        """Context manager that patches all file operations to use this mock filesystem."""
        with (
            patch.object(Filesystem, "_exists", MagicMock(side_effect=self._mock_exists)) as patch_exists,
            patch.object(Filesystem, "_is_dir", MagicMock(side_effect=self._mock_is_dir)) as patch_is_dir,
            patch.object(Filesystem, "_read_metadata", MagicMock(side_effect=self._mock_read_metadata)) as patch_read_metadata,
            patch.object(Filesystem, "_get_listing", MagicMock(side_effect=self._mock_get_listing)) as patch_get_listing,
            patch.object(Filesystem, "_read_text", MagicMock(side_effect=self._mock_read_text)) as patch_read_text,
            patch.object(Filesystem, "_read_bytes", MagicMock(side_effect=self._mock_read_bytes)) as patch_read_bytes,
            patch.object(Filesystem, "_create_directory", MagicMock(side_effect=self._mock_create_directory)) as patch_create_directory,
            patch.object(Filesystem, "_write_text", MagicMock(side_effect=self._mock_write_text)) as patch_write_text,
            patch.object(Filesystem, "_append_text", MagicMock(side_effect=self._mock_append_text)) as patch_append_text,
            patch.object(Filesystem, "_copy_file", MagicMock(side_effect=self._mock_copy_file)) as patch_copy_file,
            patch.object(Filesystem, "_copy_dir", MagicMock(side_effect=self._mock_copy_dir)) as patch_copy_dir,
            patch.object(Filesystem, "_move", MagicMock(side_effect=self._mock_move)) as patch_move,
            patch.object(Filesystem, "_get_free_space", MagicMock(side_effect=self._mock_get_free_space)) as patch_get_free_space,
            patch.object(Filesystem, "_delete_file", MagicMock(side_effect=self._mock_delete_file)) as patch_delete_file,
            patch.object(Filesystem, "_delete_dir", MagicMock(side_effect=self._mock_delete_dir)) as patch_delete_dir,
            patch.object(Filesystem, "_is_text_file", MagicMock(side_effect=self._mock_is_text_file)) as patch_is_text_file,

            patch("solveig.config.DEFAULT_CONFIG_PATH", Path("/home/_test_user_/.config.json")) as patch_default_config,
            patch("scripts.init.DEFAULT_BASHRC_PATH", Path("/home/_test_user_/.bashrc")) as patch_default_bashrc,
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
