"""
Streamlined mock file system for testing file operations without touching real files.
Only contains the essential MockFileSystem class and integrated mock methods.
"""
import datetime
import os
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch, MagicMock


class _MockFileDir:
    """Basic mock for a thing that can exist in a filesystem."""
    def __init__(self, path: str | Path, metadata: dict[str, Any] | None = None) -> None:
        # if is_directory and content:
        #     raise IsADirectoryError("Cannot write content for directory")
        # if not is_directory and listing:
        #     raise NotADirectoryError("Cannot write listing for file")

        self.path: Path =  Path(path).expanduser().absolute()
        # self.is_directory = is_directory
        self.metadata: dict[str, Any] = {
            "encoding": "utf-8",
            "mtime": str(datetime.datetime.now().isoformat()),
            "is_directory": False,
            "owner": "testuser",
            "group": "testgroup",
            "st_mtime": int(datetime.datetime.now().timestamp()),
            "st_uid": 1000,
            "st_gid": 1000,
            **(metadata or {}),
        }


class MockFile(_MockFileDir):
    def __init__(self, path: str | Path, content: str = "", metadata: dict[str, Any] | None = None) -> None:
        super().__init__(path=MockFileSystem._abs_path(path), metadata=metadata)
        self.content = content
        self.metadata.setdefault("size", len(content))
        #
        #
        # if is_directory and content:
        #     raise IsADirectoryError("Cannot write content for directory")
        # if not is_directory and listing:
        #     raise NotADirectoryError("Cannot write listing for file")
        #
        # self.path: Path = Path(path).expanduser().absolute()
        # self.is_directory = is_directory
        # self.content = content or ""
        # self.listing = listing
        # self.metadata: dict[str, Any] = {
        #     "size": len(self.content),
        #     "encoding": "utf-8",
        #     "mtime": str(datetime.datetime.now().isoformat()),
        #     "is_directory": False,
        #     "owner": "testuser",
        #     "group": "testgroup",
        #     "st_mtime": int(datetime.datetime.now().timestamp()),
        #     "st_uid": 1000,
        #     "st_gid": 1000,
        #     **(metadata or {}),
        # }


class MockDir(_MockFileDir):
    def __init__(self, path: str | Path, metadata: dict[str, Any] | None = None) -> None:
        super().__init__(path=MockFileSystem._abs_path(path), metadata=metadata)
        # self.listing = listing or []


class MockFileSystem:
    """Mock file system that simulates file operations without touching real files."""

    def __init__(self):
        self.files: dict[Path, MockDir | MockFile] = {}  # path -> {"content": str, "is_directory": bool, "metadata": dict, "listing": list}
        self.mocks = SimpleNamespace()  # Store references to mock objects for direct access
        self.reset()

    def reset(self):
        """Reset the mock file system to default test state."""
        self.files.clear()
        # Add parent directories first
        # self.add_directory(MockFileDir("/test", True))
        # Add some default test files that tests expect
        self.write_file("/test/file.txt", "test content")
        self.write_file("/test/source.txt", "source content")
        self.write_file("/test/original.txt", "original content")
        self.write_file("/test/unwanted.txt", "unwanted content")
        self.add_directory(
            "/test/dir",
            "/test/dir/subdir"
        )
        self.write_file("/test/dir/nested.txt")

    @staticmethod
    def _abs_path(path: str | Path) -> Path:
        """Convert path to absolute path string."""
        return Path(path).expanduser().absolute()
    
    def exists(self, path: str | Path) -> bool:
        """Check if a path exists in the mock file system."""
        abs_path = self._abs_path(path)
        return abs_path in self.files

    def _get(self, path: str | Path) -> MockFile | MockDir:
        abs_path = self._abs_path(path)
        try:
            return self.files[abs_path]
        except KeyError:
            raise FileNotFoundError(f"File or directory does not exist: {abs_path}")

    # def write_file(self, path: str | Path, content: str = "", metadata: dict[str, Any] = None):
    def write_file(self, path: str | Path, content: str = "", metadata: dict[str, Any] | None = None, **kwargs) -> None:
        """Add a mock file to the file system if it doesn't exist and write content into it."""
        file = MockFile(path=path, content=content, metadata=metadata)
        if not self.exists(file.path.parent):
            self.add_directory(file.path.parent)
        self.files[file.path] = file

        # self.files[abs_path] = {
        #     "content": content,
        #     "is_directory": False,
        #     "metadata": {
        #         "path": abs_path,
        #         "size": len(content),
        #         "encoding": encoding,
        #         "mtime": str(datetime.datetime.now().isoformat()),
        #         "is_directory": False,
        #         "owner": "testuser",
        #         "group": "testgroup",
        #         "st_mtime": int(datetime.datetime.now().timestamp()),  # Fixed timestamp for testing
        #         "st_uid": 1000,  # Fixed uid for testing
        #         "st_gid": 1000,  # Fixed gid for testing
        #         **(metadata or {}),
        #     },
        #     "listing": None,
        # }

    # def add_directory(
    #     self,
    #     path: str | Path,
    #     listing: list[MockFileDir] = None,
    #     exist_ok=True,
    #     metadata: dict = None,
    # ):
    def add_directory(self, path: Path | str, parents=True, *sub_dirs: list[MockDir | MockFile], metadata: dict[str, Any] | None = None, exist_ok=True):
    # def add_directory(self, directory: MockDir, listing: list[MockDir | MockFile] | None = None, exist_ok=True):
        """Mock Path.mkdir() to create directory in MockFileSystem"""
        abs_path = self._abs_path(path)
        if self.exists(abs_path):
            if not exist_ok:
                raise FileExistsError(f"Directory exists: '{abs_path}'")
            return

        # If the parent directory doesn't exist, and we're not at the top
        # add the parent directory first - recurse "upwards"
        if not self.exists(abs_path.parent):
            if not parents:
                raise FileNotFoundError(f"Directory does not exist: {abs_path.parent}")
            elif abs_path != abs_path.parent:
                self.add_directory(abs_path.parent)
            # # Create all parent directories
            # parent_path = str(abs_path.parent)
            # if parent_path != abs_path and not self.exists(parent_path):
            #     self.add_directory(parent_path)

        self.files[abs_path] = MockDir(path=abs_path, metadata=metadata) # MockFileDir(abs_path, is_directory=True, listing=listing, metadata=metadata)

        # Add the sub-paths
        for file in sub_dirs or []:
            # if isinstance(abs_path, dict):
            #     file = MockFileDir(**file)
            if isinstance(file, MockDir):
                self.add_directory(file)
            else:
                self.write_file(file)


        # self.add_directory(str(path))

        # abs_path = self._abs_path(path)
        # self.files[abs_path] = {
        #     "content": None,
        #     "is_directory": True,
        #     "metadata": {
        #         "path": abs_path,
        #         "size": 0,
        #         "mtime": "2024-01-01T00:00:00",
        #         "is_directory": True,
        #         "owner": "testuser",
        #         "group": "testgroup",
        #         **(metadata or {}),
        #     },
        #     "listing": listing or [],
        # }

    def is_directory(self, path: str | Path) -> bool:
        """Check if a path is a directory in the mock file system."""
        return self.exists(path) and isinstance(self._get(path), MockDir)
        # abs_path = self._abs_path(path)
        # return self.files.get(abs_path, {}).get("is_directory", False)

    def is_file(self, path: str | Path) -> bool:
        """Check if a path is a file in the mock file system."""
        return self.exists(path) and isinstance(self._get(path), MockFile)
        # abs_path = self._abs_path(path)
        # return self.files.get(abs_path, {}).get("is_directory", True)

    def get_content(self, path: str | Path, **kwargs) -> str | bytes:
        """Get content of a file in the mock file system."""
        file = self._get(path)
        if not isinstance(file, MockFile):
            raise IsADirectoryError(f"Cannot read directory content: {file.path}")
        content = file.content
        if "encoding" in kwargs:
            content = content.encode(kwargs["encoding"])
        return content
        # abs_path = self._abs_path(path)
        # if not self.is_file(abs_path):
        #
        # return self._get(path).content

    # def get_bytes(self, path: str | Path, encoding = "utf-8") -> str | bytes:


    def _copy_or_cove(self, src, dst, move=False):
        """Mock shutil.move() to move files in MockFileSystem"""
        src_path = self._abs_path(src)
        dst_path = self._abs_path(dst)

        # # Move the file/directory
        # self.files[dst_path] = self._get(src_path)
        # del self.files[src_path]

        # Find the path and all sub-paths to copy/move
        # make a copy to avoid modification during iteration
        files_to_move = []
        for file_path, file_data in self.files.items():
            if file_path == src_path or file_path.is_relative_to(src_path):
                # Replace src prefix with dst prefix
                new_path = self._abs_path(str(file_path).replace(str(src_path), str(dst_path), 1))
                # Update path in metadata
                file_data.path = new_path
                files_to_move.append((src_path, new_path))

        # Now add the copied files
        for from_path, to_path in files_to_move:
            self.files[to_path] = self.files[from_path]
            # If we're moving, delete the original
            if move:
                del self.files[from_path]
            # if file_data["is_directory"]:
            #     self.add_directory(new_path)
            # else:
            #     self.add_file(new_path, file_data["content"])

        # Update the path in metadata
        # self.files[dst_path]["metadata"]["path"] = dst_path

    # ===================================================================
    # MOCK METHODS - These are used as Path method replacements
    # ===================================================================

    # def mock_path_is_file(self, path_self) -> bool:
    #     """Mock Path.is_file() to check MockFileSystem"""
    #     abs_path = self._abs_path(str(path_self))
    #     if not self.exists(str(path_self)):
    #         return False
    #     return not self.files[abs_path]["is_directory"]
    #
    # def mock_path_is_dir(self, path_self) -> bool:
    #     """Mock Path.is_dir() to check MockFileSystem"""
    #     return self.is_directory(str(path_self))

    def mock_path_stat(self, path: str | Path):
        """Mock Path.stat() to return MockFileSystem metadata"""
        abs_path = self._abs_path(path)
        if not self.exists(abs_path):
            raise FileNotFoundError(f"No such file or directory: '{abs_path}'")

        metadata = self.files[abs_path].metadata
        # Return a simple object with the stat fields that are actually used
        return SimpleNamespace(
            st_size=metadata.get("size", 0),
            st_mtime=metadata.get("st_mtime"),
            st_uid=metadata.get("st_uid", 1000),
            st_gid=metadata.get("st_gid", 1000)
        )

    def mock_path_iterdir(self, path: str | Path) -> list[Path]:
        """Mock Path.iterdir() to return MockFileSystem directory listing"""
        abs_path = self._abs_path(path)
        file_data = self._get(abs_path)
        if isinstance(file_data, MockFile):
            raise NotADirectoryError(f"Not a directory: '{abs_path}'")

        # Let's not have a .listing field that duplicates information from the MockFilesystem. Keep it simple.
        # This will never be used at a large scale. Check sub-paths by iterating over the filesystem and checking
        listing = [
            other_path
            for other_path in self.files
            if other_path.parent == abs_path
        ]
        return listing

    # def mock_path_read_text(self, path: str | Path):
    #     """Mock Path.read_text() to read from MockFileSystem"""
    #     file_data = self._get(path)
    #     if file_data.is_directory:
    #         raise IsADirectoryError(f"Is a directory: '{self._abs_path(path)}'")
    #     return file_data.content

    # def mock_path_read_bytes(self, path):
    #     """Mock Path.read_bytes() to read from MockFileSystem"""
    #     abs_path = self._abs_path(path)
    #     file_data = self._get(abs_path)
    #     if file_data.is_directory:
    #         raise IsADirectoryError(f"Is a directory: '{abs_path}'")
    #
    #     # Return bytes version of content
    #     return file_data.content.encode("utf-8")

    # def mock_path_write_text(self, path, content, encoding="utf-8"):
    #     """Mock Path.write_text() to write to MockFileSystem"""
    #     abs_path = self._abs_path(path)
    #     # Ensure parent directory exists in mock system
    #     if not self.exists(abs_path.parent):
    #         self.add_directory(abs_path.parent)
    #
    #     self.add_file(abs_path, content)

    # def mock_path_mkdir(self, path, parents=False, exist_ok=False, **kwargs):
    #     """Mock Path.mkdir() to create directory in MockFileSystem"""
    #     abs_path = self._abs_path(str(path))
    #
    #     if self.exists(abs_path):
    #         if not exist_ok:
    #             raise FileExistsError(f"File exists: '{abs_path}'")
    #         return
    #
    #     if parents:
    #         # Create all parent directories
    #         parent_path = str(abs_path.parent)
    #         if parent_path != abs_path and not self.exists(parent_path):
    #             self.add_directory(parent_path)
    #
    #     self.add_directory(str(path))

    def mock_path_unlink(self, path):
        """Mock Path.unlink() to delete file from MockFileSystem"""
        abs_path = self._abs_path(path)
        file_data = self._get(abs_path)
        if isinstance(file_data, MockDir):
            raise IsADirectoryError(f"Is a directory: '{abs_path}'")
        del self.files[abs_path]

    # System Operations
    def mock_shutil_rmtree(self, path, ignore_errors=False, onexc=None, onerror=None, dir_fd=None):
        """Mock shutil.rmtree() to remove directory tree from MockFileSystem"""
        abs_path = self._abs_path(path)
        if not self.exists(abs_path):
            raise FileNotFoundError(f"No such file or directory: '{abs_path}'")

        # Remove the directory and all children
        to_remove = [abs_path]
        for file_path in self.files.keys():
            if file_path.is_relative_to(abs_path):
                to_remove.append(file_path)

        for path_to_remove in to_remove:
            if path_to_remove in self.files:
                del self.files[path_to_remove]

    def copy(self, src, dst):
        return self._copy_or_cove(src, dst, move=False)

    def move(self, src, dst):
        return self._copy_or_cove(src, dst, move=True)

    # def mock_shutil_copy2(self, src, dst):
    #     """Mock shutil.copy2() to copy files in MockFileSystem"""
    #     src_path = self._abs_path(src)
    #     dst_path = self._abs_path(dst)
    #
    #     if not self.exists(src_path):
    #         raise FileNotFoundError(f"No such file or directory: '{src_path}'")
    #
    #     file_data = self.files[src_path]
    #     if file_data["is_directory"]:
    #         raise IsADirectoryError(f"Is a directory: '{src_path}'")
    #
    #     # Copy the file
    #     self.add_file(dst_path, file_data.content)

    # def mock_shutil_copytree(self, src, dst):
    #     """Mock shutil.copytree() to copy directory trees in MockFileSystem"""
    #     src_path = self._abs_path(src)
    #     dst_path = self._abs_path(dst)
    #
    #     if not self.exists(src_path):
    #         raise FileNotFoundError(f"No such file or directory: '{src_path}'")
    #
    #     # Copy the directory and all contents - make a copy to avoid modification during iteration
    #     files_to_copy = []
    #     for file_path, file_data in self.files.items():
    #         if file_path.startswith(src_path):
    #             # Replace src prefix with dst prefix
    #             new_path = file_path.replace(src_path, dst_path, 1)
    #             files_to_copy.append((new_path, file_data))
    #
    #     # Now add the copied files
    #     for new_path, file_data in files_to_copy:
    #         if file_data["is_directory"]:
    #             self.add_directory(new_path)
    #         else:
    #             self.add_file(new_path, file_data["content"])

    def mock_os_access(self, path, mode) -> bool:
        """Mock os.access() to check MockFileSystem permissions"""
        abs_path = self._abs_path(path)
        if not self.exists(path):
            return False

        file_data = self._get(abs_path)

        # Check readable permission
        if mode & os.R_OK and file_data.metadata.get("readable") is False:
            return False

        # Check writable permission
        if mode & os.W_OK and file_data.metadata.get("writable") is False:
            return False

        return True

    def mock_shutil_disk_usage(self, path):
        """Mock shutil.disk_usage() for disk space testing"""
        DiskUsage = namedtuple("DiskUsage", "total used free")

        # Return large disk space by default, tests can override via metadata
        abs_path = self._abs_path(path)
        try:
            file_data = self._get(abs_path)
            free_space = file_data.metadata.get("disk_free", 1000000000)  # 1GB default
        except FileNotFoundError:
            free_space = 1000000000  # 1GB default

        return DiskUsage(total=2000000000, used=1000000000, free=free_space)

    # System Info Operations
    def mock_pwd_getpwuid(self, path):
        """Mock pwd.getpwuid() to return test user info"""
        return SimpleNamespace(pw_name=self._get(path).metadata["owner"])

    def mock_grp_getgrgid(self, path):
        """Mock grp.getgrgid() to return test group info"""
        return SimpleNamespace(gr_name=self._get(path).metadata["owner"])

    _TEXT_FILE_EXTENSIONS = {
        "txt", "json", "py", "json", "js"
    }

    def mock_mimetypes_guess_type(self, path):
        """Mock mimetypes.guess_type() for consistent testing"""
        if any(str(path).endswith(f".{sig}") for sig in self._TEXT_FILE_EXTENSIONS):
            return ("text/plain", None)
        else:
            return ("application/octet-stream", None)

    @contextmanager
    def patch_all_file_operations(self):
        """Context manager that patches all file operations to use this mock filesystem."""
        with (
            patch.object(Path, "exists", lambda path: self.exists(path)) as patch_exists,
            patch.object(Path, "is_file", lambda path: self.is_file(path)) as patch_is_file,
            patch.object(Path, "is_dir", lambda path: self.is_directory(path)) as patch_is_dir,
            patch.object(Path, "stat", lambda path: self.mock_path_stat(path)) as patch_stat,
            patch.object(Path, "iterdir", lambda path: self.mock_path_iterdir(path)) as patch_iterdir,
            patch.object(Path, "read_text", lambda path, **kwargs: self.get_content(path, **kwargs)) as patch_read_text,
            patch.object(Path, "read_bytes", lambda path, encoding="utf-8",**kwargs: self.get_content(path, encoding=encoding, **kwargs)) as patch_read_bytes,
            patch.object(Path, "write_text", lambda path, content, **kwargs: self.write_file(path, content=content, **kwargs)) as patch_write_text,
            patch.object(Path, "mkdir", lambda path, **kwargs: self.add_directory(path, **kwargs)) as patch_mkdir,
            patch.object(Path, "unlink", lambda path: self.mock_path_unlink(path)) as patch_unlink,
            patch("shutil.rmtree", lambda path: self.mock_shutil_rmtree(path)) as patch_rmtree,
            patch("shutil.move", lambda src_path, dest_path: self.move(src_path, dest_path)) as patch_move,
            patch("shutil.copy2", lambda src_path, dest_path: self.copy(src_path, dest_path)) as patch_copy2,
            patch("shutil.copytree", lambda src_path, dest_path: self.copy(src_path, dest_path)) as patch_copytree,
            patch("os.access", lambda path, mode: self.mock_os_access(path, mode)) as patch_access,
            patch("shutil.disk_usage", lambda path: self.mock_shutil_disk_usage(path)) as patch_disk_usage,
            patch("pwd.getpwuid", lambda path: self.mock_pwd_getpwuid(path)) as patch_getpwuid,
            patch("grp.getgrgid", lambda path: self.mock_grp_getgrgid(path)) as patch_getgrgid,
            patch("mimetypes.guess_type", lambda path: self.mock_mimetypes_guess_type(path)) as patch_guess_type,
        ):
            # Reset to clean state
            self.reset()
            
            # Store mock references in a namespace for direct access in tests
            self.mocks = SimpleNamespace(
                mkdir=patch_mkdir,
                write_text=patch_write_text,
                read_text=patch_read_text,
                exists=patch_exists,
                is_file=patch_is_file,
                is_dir=patch_is_dir,
                unlink=patch_unlink,
                rmtree=patch_rmtree,
                move=patch_move,
                copy2=patch_copy2,
                disk_usage=patch_disk_usage,
            )
            
            yield self


# Global mock file system instance
mock_fs = MockFileSystem()