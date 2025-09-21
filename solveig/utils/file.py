import base64
import grp
import os
import pwd
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Literal

from pydantic import Field

from solveig.utils.misc import parse_human_readable_size


@dataclass
class Metadata:
    owner_name: str
    group_name: str
    path: PurePath
    size: int
    is_directory: bool
    is_readable: bool
    is_writable: bool
    modified_time: int = Field(
        ...,
        description="Last modified time for file or dir as UNIX timestamp",
    )
    encoding: Literal["text", "base64"] | None = None  # set after reading a file
    listing: dict[PurePath, "Metadata"] | None = None


@dataclass
class FileContent:
    content: str | bytes
    encoding: Literal["text", "base64"]


class Filesystem:
    """
    Filesystem operations with three main sections:
    - Private: Low-level filesystem operations (mocked in tests)
    - Validation: Access and permission checking
    - Operations: Public API for file/directory operations
    """

    # =============================================================================
    # PRIVATE - Low-level filesystem operations
    # =============================================================================
    # These directly interact with filesystem and are all mocked in unit tests
    # Do not perform path normalization or validation

    @staticmethod
    def _get_listing(abs_path: PurePath) -> list[PurePath]:
        return sorted(Path(abs_path).iterdir())

    @staticmethod
    def _read_text(abs_path: PurePath) -> str:
        return Path(abs_path).read_text()

    @staticmethod
    def _read_bytes(abs_path: PurePath) -> bytes:
        return Path(abs_path).read_bytes()

    @staticmethod
    def _create_directory(abs_path: PurePath) -> None:
        Path(abs_path).mkdir()

    @staticmethod
    def _write_text(abs_path: PurePath, content: str = "", encoding="utf-8") -> None:
        Path(abs_path).write_text(content, encoding=encoding)

    @staticmethod
    def _append_text(abs_path: PurePath, content: str = "", encoding="utf-8") -> None:
        with open(abs_path, "a", encoding=encoding) as fd:
            fd.write(content)

    @staticmethod
    def _copy_file(abs_src_path: PurePath, abs_dest_path: PurePath) -> None:
        shutil.copy2(abs_src_path, abs_dest_path)

    @staticmethod
    def _copy_dir(src_path: PurePath, dest_path: PurePath) -> None:
        shutil.copytree(src_path, dest_path)

    @staticmethod
    def _move(src_path: PurePath, dest_path: PurePath) -> None:
        shutil.move(src_path, dest_path)

    @staticmethod
    def _get_free_space(abs_path: PurePath) -> int:
        return shutil.disk_usage(abs_path).free

    @staticmethod
    def _delete_file(abs_path: PurePath) -> None:
        Path(abs_path).unlink()

    @staticmethod
    def _delete_dir(abs_path: PurePath) -> None:
        shutil.rmtree(abs_path)

    @staticmethod
    def _is_text_file(abs_path: PurePath, _blocksize: int = 512) -> bool:
        """
        Believe it or not, the most reliable way to tell if a real file
        is to read a piece of it and find b'\x00'
        """
        with Path(abs_path).open("rb") as fd:
            chunk = fd.read(_blocksize)
            if b"\x00" in chunk:
                return False
            try:
                chunk.decode("utf-8")
                return True
            except UnicodeDecodeError:
                try:
                    chunk.decode("utf-16")
                    return True
                except UnicodeDecodeError:
                    return False

    @classmethod
    def _closest_writable_parent(cls, abs_dir_path: PurePath) -> PurePath | None:
        """
        Check that a directory can be created by walking up the tree
        until we find an existing directory and checking its permissions.
        """
        while True:
            if cls.exists(abs_dir_path):
                return abs_dir_path if cls.is_writable(abs_dir_path) else None
            # Reached root dir without being writable
            if abs_dir_path == abs_dir_path.parent:
                return None
            abs_dir_path = abs_dir_path.parent

    # =============================================================================
    # VALIDATION - Access and permission checking
    # =============================================================================

    @classmethod
    def validate_read_access(cls, file_path: str | PurePath) -> None:
        """
        Validate that a file can be read.

        Args:
            file_path: Source file path

        Raises:
            FileNotFoundError: If trying to read a non-existing file
            PermissionError: If file is not readable
        """
        abs_path = cls.get_absolute_path(file_path)
        if not cls.exists(abs_path):
            raise FileNotFoundError(f"Path {abs_path} does not exist")
        if not cls.is_readable(abs_path):
            raise PermissionError(f"Path {abs_path} is not readable")

    @classmethod
    def validate_delete_access(cls, path: str | PurePath) -> None:
        """
        Validate that a file or directory can be deleted.

        Args:
            path: Source file/directory path

        Raises:
            FileNotFoundError: If trying to delete a non-existing file
            PermissionError: If parent directory is not writable
        """
        abs_path = cls.get_absolute_path(path)
        if not cls.exists(abs_path):
            raise FileNotFoundError(f"File {abs_path} does not exist")
        if not cls.is_writable(abs_path.parent):
            raise PermissionError(f"File {abs_path.parent} is not writable")

    @classmethod
    def validate_write_access(
        cls,
        path: str | PurePath,
        content: str | bytes | None = None,
        content_size: int | None = None,
        min_disk_size_left: str | int = 0,
    ) -> None:
        """
        Validate that a file or directory can be written.

        Args:
            path: Source file/directory path
            content: Content to write (for size calculation)
            content_size: Optional size to be written (omitted for directories)
            min_disk_size_left: Optional minimum disk space left in bytes after writing

        Raises:
            IsADirectoryError: If trying to overwrite an existing directory
            PermissionError: If parent directory cannot be created or is not writable
            OSError: If there would not be enough disk space left after writing
        """
        abs_path = cls.get_absolute_path(path)
        min_disk_bytes_left = parse_human_readable_size(min_disk_size_left)

        # Check if path already exists
        if cls.exists(abs_path):
            if cls.is_dir(abs_path):
                raise IsADirectoryError(
                    f"Cannot overwrite existing directory {abs_path}"
                )
            elif not cls.is_writable(abs_path):
                raise PermissionError(f"Cannot write into file {abs_path}")

        # Find the closest writable parent for new files/directories
        closest_writable_parent = cls._closest_writable_parent(abs_path.parent)
        if not closest_writable_parent:
            raise PermissionError(f"Cannot create parent directory {abs_path.parent}")

        # Check disk space
        if not content_size and content is not None:
            content_size = len(
                content.encode("utf-8") if isinstance(content, str) else content
            )
        if content_size is not None:
            free_space = cls._get_free_space(closest_writable_parent)
            free_after_write = free_space - content_size
            if free_after_write <= min_disk_bytes_left:
                raise OSError(
                    f"Insufficient disk space: After writing {content_size} bytes to {abs_path}, "
                    f"only {free_after_write} bytes would be available, minimum configured is {min_disk_bytes_left} bytes"
                )

    # =============================================================================
    # OPERATIONS - Public API for file/directory operations
    # =============================================================================
    # These perform validation and accept string/relative paths
    # Some of these are mocked in unit tests

    @staticmethod
    def get_absolute_path(path: str | PurePath) -> PurePath:
        """
        Convert path to absolute path with user expansion.
        We expand into the real path and return a PurePath that can't do filesystem operations.
        """
        return PurePath(Path(path).expanduser().resolve())

    @staticmethod
    def exists(abs_path: PurePath) -> bool:
        """Check if path exists."""
        return Path(abs_path).exists()

    @staticmethod
    def is_dir(abs_path: PurePath) -> bool:
        """Check if path is a directory."""
        return Path(abs_path).is_dir()

    @classmethod
    def is_readable(cls, abs_path: PurePath) -> bool:
        """Check if path is readable."""
        try:
            return cls.read_metadata(abs_path, descend_level=0).is_readable
        except (PermissionError, OSError):
            return False

    @classmethod
    def is_writable(cls, abs_path: PurePath) -> bool:
        """Check if path is writable."""
        try:
            return cls.read_metadata(abs_path, descend_level=0).is_writable
        except (PermissionError, OSError):
            return False

    @classmethod
    def read_metadata(cls, abs_path: PurePath, descend_level=1) -> Metadata:
        """
        Read metadata and dir structure from filesystem.

        Args:
            abs_path: The absolute path to read metadata from
            descend_level: How far down to read (0=current only, 1=first level, -1=entire tree)

        Returns:
            Metadata object with file/directory information
        """
        abs_path = Path(abs_path)
        stats = abs_path.stat()

        is_dir = cls.is_dir(abs_path)
        if is_dir and descend_level != 0:
            listing = {
                sub_path: cls.read_metadata(sub_path, descend_level=descend_level - 1)
                for sub_path in sorted(
                    [cls.get_absolute_path(sub_path) for sub_path in abs_path.iterdir()]
                )
            }
        else:
            listing = None

        return Metadata(
            path=PurePath(abs_path),
            size=stats.st_size,
            modified_time=int(stats.st_mtime),
            is_directory=is_dir,
            owner_name=pwd.getpwuid(stats.st_uid).pw_name,
            group_name=grp.getgrgid(stats.st_gid).gr_name,
            is_readable=os.access(abs_path, os.R_OK),
            is_writable=os.access(abs_path, os.W_OK),
            listing=listing,
        )

    @classmethod
    def read_file(cls, path: str | PurePath) -> FileContent:
        """
        Read file contents with automatic text/binary detection.

        Args:
            path: File path to read

        Returns:
            FileContent with content and encoding type
        """
        abs_path = cls.get_absolute_path(path)
        cls.validate_read_access(abs_path)
        if cls.is_dir(abs_path):
            raise IsADirectoryError(f"Cannot read directory {abs_path}")

        try:
            if cls._is_text_file(abs_path):
                return FileContent(content=cls._read_text(abs_path), encoding="text")
            else:
                raise Exception("utf-8", None, 0, -1, "Fallback to Base64")
        except Exception:
            return FileContent(
                content=base64.b64encode(cls._read_bytes(abs_path)).decode("utf-8"),
                encoding="base64",
            )

    @classmethod
    def write_file(
        cls,
        file_path: str | PurePath,
        content: str = "",
        encoding: str = "utf-8",
        min_space_left: int = 0,
        append=False,
    ) -> None:
        """Write content to file with validation and parent directory creation."""
        abs_path = cls.get_absolute_path(file_path)
        size = len(content.encode(encoding))
        cls.validate_write_access(
            abs_path, content_size=size, min_disk_size_left=min_space_left
        )
        cls.create_directory(abs_path.parent, exist_ok=True)

        if append and cls.exists(abs_path):
            cls._append_text(abs_path, content, encoding=encoding)
        else:
            cls._write_text(abs_path, content, encoding=encoding)

    @classmethod
    def create_directory(cls, dir_path: str | PurePath, exist_ok=True) -> None:
        """Create directory with recursive parent creation."""
        abs_path = cls.get_absolute_path(dir_path)
        if cls.exists(abs_path):
            if exist_ok:
                return
            else:
                raise PermissionError(f"Directory {abs_path} already exists")
        else:
            # Recursively create parent directories
            if abs_path != abs_path.parent and not cls.exists(abs_path.parent):
                cls.create_directory(abs_path.parent, exist_ok=True)
            cls._create_directory(abs_path)

    @classmethod
    def copy(
        cls, src_path: str | PurePath, dest_path: str | PurePath, min_space_left: int
    ) -> None:
        """Copy file or directory with validation."""
        src_path = cls.get_absolute_path(src_path)
        dest_path = cls.get_absolute_path(dest_path)

        src_size = cls.read_metadata(src_path, descend_level=0).size
        cls.validate_read_access(src_path)
        cls.validate_write_access(
            dest_path, content_size=src_size, min_disk_size_left=min_space_left
        )
        cls.create_directory(dest_path.parent)

        if cls.is_dir(src_path):
            cls._copy_dir(src_path, dest_path)
        else:
            cls._copy_file(src_path, dest_path)

    @classmethod
    def move(cls, src_path: str | PurePath, dest_path: str | PurePath) -> None:
        """Move file or directory with validation."""
        src_path = cls.get_absolute_path(src_path)
        dest_path = cls.get_absolute_path(dest_path)

        cls.validate_read_access(src_path)
        cls.validate_write_access(dest_path)
        cls.create_directory(dest_path.parent)

        cls._move(src_path, dest_path)

    @classmethod
    def delete(cls, path: str | PurePath) -> None:
        """Delete file or directory with validation."""
        abs_path = cls.get_absolute_path(path)
        cls.validate_delete_access(abs_path)
        if cls.is_dir(abs_path):
            cls._delete_dir(abs_path)
        else:
            cls._delete_file(abs_path)

    @classmethod
    def path_matches_patterns(
        cls, abs_path: PurePath, patterns: list[PurePath]
    ) -> bool:
        """Check if a file path matches any of the given glob patterns.

        Args:
            abs_path: The path to check
            patterns: List of glob patterns already expanded (e.g., ['/home/user/Documents/**/*.py', '/tmp/*'])

        Returns:
            True if the path matches any pattern, False otherwise
        """
        return any(abs_path.full_match(pattern) for pattern in patterns)
