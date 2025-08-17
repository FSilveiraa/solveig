import base64
import grp
import os
import pwd
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# class Filesystem:
#     _SIZE_NOTATIONS = {
#         "kib": 1024,
#         "mib": 1024 ** 2,
#         "gib": 1024 ** 3,
#         "tib": 1024 ** 4,
#         "kb": 1000,
#         "mb": 1000 ** 2,
#         "gb": 1000 ** 3,
#         "tb": 1000 ** 4,
#     }
#
#     _SIZE_PATTERN = re.compile(r"^\s*(?P<size>\d+(?:\.\d+)?)\s*(?P<unit>\w+)\s*$")
#
#
#     @staticmethod
#     def absolute_path(path: str | Path) -> Path:
#         return Path(path).expanduser().resolve()
#
#     @classmethod
#     def parse_size_notation_into_bytes(cls, size_notation: int | str | None) -> int:
#         if size_notation is not None:
#             if isinstance(size_notation, int):
#                 return size_notation
#             else:
#                 try:
#                     return int(size_notation)
#                 except ValueError:
#                     try:
#                         match_result = cls._SIZE_PATTERN.match(size_notation)
#                         if match_result is None:
#                             raise ValueError(f"'{size_notation}' is not a valid disk size")
#                         size, unit = match_result.groups()
#                         unit = unit.strip().lower()
#                         try:
#                             return int(float(size) * cls._SIZE_NOTATIONS[unit])
#                         except KeyError:
#                             supported = [
#                                 f"{supported_unit[0].upper()}{supported_unit[1:-1]}{supported_unit[-1].upper()}"
#                                 for supported_unit in cls._SIZE_NOTATIONS
#                             ]
#                             raise ValueError(
#                                 f"'{unit}' is not a valid disk size unit. Supported: {supported}"
#                             ) from None
#                     except (AttributeError, ValueError):
#                         raise ValueError(
#                             f"'{size_notation}' is not a valid disk size"
#                         ) from None
#         return 0  # to be on the safe size, since this is used when checking if a write operation can proceed, assume None = 0
#
#     @classmethod
#     def read_metadata_and_listing(cls, path: str | Path, _descend=True):
#         # TODO: should be separate methods
#         abs_path = cls.absolute_path(path)
#         if not abs_path.exists():
#             raise FileNotFoundError(f"{path} does not exist")
#
#         stats = abs_path.stat()
#         # resolve uid/gid to names
#         owner_name = pwd.getpwuid(stats.st_uid).pw_name
#         group_name = grp.getgrgid(stats.st_gid).gr_name
#
#         metadata = {
#             "path": str(abs_path),
#             "size": stats.st_size,
#             "mtime": time.ctime(stats.st_mtime),
#             "is_directory": abs_path.is_dir(),
#             "owner": owner_name,
#             "group": group_name,
#         }
#         entries = None
#
#         if abs_path.is_dir() and _descend:
#             # For a directory, list entries (including hidden)
#             entries = []
#             for name in sorted(abs_path.iterdir()):
#                 # entry_path = os.path.join(path, name)
#                 entry_path = abs_path.joinpath(name).resolve()
#                 # entry_stats = os.stat(entry_path)
#                 # read the metadata for each entry using this same method with going further down
#                 entries.append(cls.read_metadata_and_listing(entry_path, _descend=False)[0])
#         return metadata, entries
#
#     @classmethod
#     def read_file_as_base64(cls, path: str | Path) -> str:
#         abs_path = cls.absolute_path(path)
#         return base64.b64encode(abs_path.read_bytes()).decode("utf-8")
#
#     @classmethod
#     def read_file_as_text(cls, path: str | Path) -> str:
#         abs_path = cls.absolute_path(path)
#         return abs_path.read_text()
#
#     @classmethod
#     def read_file(cls, path: str | Path) -> tuple[str, Literal["text", "base64"]]:
#         abs_path = cls.absolute_path(path)
#         if abs_path.is_dir():
#             raise FileNotFoundError(f"{abs_path} is a directory")
#
#         mime, _ = mimetypes.guess_type(path)
#         try:
#             if mime and mime.startswith("text") or mime == "application/x-sh":
#                 return (cls.read_file_as_text(abs_path), "text")
#             else:
#                 raise UnicodeDecodeError("utf-8", b"", 0, 1, "Fallback to base64")
#         except (UnicodeDecodeError, Exception):
#             return (cls.read_file_as_base64(abs_path), "base64")
#
#     @classmethod
#     def validate_read_access(cls, file_path: str | Path) -> None:
#         """
#         Validate that a file/directory can be read.
#         Raises appropriate exceptions if validation fails.
#         """
#         abs_path = cls.absolute_path(file_path)
#
#         if not abs_path.exists():
#             raise FileNotFoundError("This path doesn't exist")
#
#         if not os.access(abs_path, os.R_OK):
#             raise PermissionError(f"Permission denied: Cannot read '{abs_path}'")
#
#     @classmethod
#     def validate_write_access(
#             cls,
#             file_path: str | Path,
#             is_directory: bool = False,
#             content: str | None = None,
#             min_disk_size_left: str | int | None = None,
#     ) -> None:
#         """
#         Validate write operation before attempting it.
#         Raises appropriate exceptions if validation fails.
#         """
#         abs_path = cls.absolute_path(file_path)
#         min_disk_bytes_left = cls.parse_size_notation_into_bytes(min_disk_size_left)
#
#         # Check if path already exists
#         if abs_path.exists():
#             if is_directory:
#                 raise FileExistsError("This directory already exists")
#             # For files, we might want to allow overwriting - let caller decide
#
#         # Check parent directory exists and is writable
#         if not parent_dir.exists():
#             # Parent will be created, check if we can create it
#             if not cls._check_can_create_parent(parent_dir):
#                 raise PermissionError(
#                     f"Cannot create parent directory '{parent_dir}': permission denied"
#                 )
#         else:
#             # Parent exists, check if we can write to it
#             if not os.access(parent_dir, os.W_OK):
#                 raise PermissionError(
#                     f"Permission denied: Cannot write to directory '{parent_dir}'"
#                 )
#
#         # Check available disk space for file writes
#         if not is_directory and content:
#             try:
#                 content_size = len(content.encode("utf-8"))
#                 available_space = shutil.disk_usage(parent_dir).free
#                 available_after_write = available_space - content_size
#                 if available_after_write < min_disk_bytes_left:
#                     raise OSError(
#                         f"Insufficient disk space: After writing {content_size} bytes, only {available_after_write} bytes would be available, minimum configured is {min_disk_bytes_left} bytes"
#                     )
#             except OSError as e:
#                 raise OSError(f"Cannot check disk space: {e}") from e
#
#     @classmethod
#     def write_file_or_directory(
#             cls, file_path: str | Path, is_directory: bool = False, content: str = ""
#     ) -> None:
#         """
#         Write a file or create a directory.
#         Raises exceptions on errors - caller handles error wrapping.
#         """
#         abs_path = cls.absolute_path(file_path)
#
#         if is_directory:
#             # Create directory
#             abs_path.mkdir(parents=True, exist_ok=False)
#         else:
#             # Ensure parent directory exists
#             if not abs_path.parent.exists():
#                 abs_path.parent.mkdir(parents=True, exist_ok=True)
#
#             # Write file content
#             abs_path.write_text(content, encoding="utf-8")
#
#     @staticmethod
#     def _check_can_create_parent(parent_dir: Path) -> bool:
#         """
#         Check if we can create a parent directory by walking up the tree
#         until we find an existing directory and checking its permissions.
#         """
#         current = parent_dir
#         while current != current.parent:  # Stop at root
#             if current.exists():
#                 return os.access(current, os.W_OK)
#             current = current.parent
#         return False  # Reached root without finding writable directory
#
#     @classmethod
#     def validate_move_access(cls, source_path: str | Path, dest_path: str | Path) -> None:
#         """
#         Validate that a move operation can be performed.
#
#         Args:
#             source_path: Source file/directory path
#             dest_path: Destination path
#
#         Raises:
#             FileNotFoundError: If source doesn't exist
#             PermissionError: If insufficient permissions
#             OSError: If destination exists or other OS error
#         """
#         source = cls.absolute_path(source_path)
#         dest = cls.absolute_path(dest_path)
#
#         # Check source exists and is readable
#         if not source.exists():
#             raise FileNotFoundError(f"Source path does not exist: {source_path}")
#
#         if not os.access(source, os.R_OK):
#             raise PermissionError(f"No read permission for source: {source_path}")
#
#         # Check we can delete from source directory
#         if not os.access(source.parent, os.W_OK):
#             raise PermissionError(
#                 f"No write permission in source directory: {source.parent}"
#             )
#
#         # Check destination doesn't exist
#         if dest.exists():
#             raise OSError(f"Destination already exists: {dest_path}")
#
#         # Check we can write to destination directory
#         dest_parent = dest.parent
#         if dest_parent.exists():
#             if not os.access(dest_parent, os.W_OK):
#                 raise PermissionError(
#                     f"No write permission in destination directory: {dest_parent}"
#                 )
#         else:
#             # Check if we can create the parent directory
#             if not cls._check_can_create_parent(dest_parent):
#                 raise PermissionError(f"Cannot create destination directory: {dest_parent}")
#
#     @classmethod
#     def validate_copy_access(cls, source_path: str | Path, dest_path: str | Path) -> None:
#         """
#         Validate that a copy operation can be performed.
#
#         Args:
#             source_path: Source file/directory path
#             dest_path: Destination path
#
#         Raises:
#             FileNotFoundError: If source doesn't exist
#             PermissionError: If insufficient permissions
#             OSError: If destination exists or other OS error
#         """
#         source = cls.absolute_path(source_path)
#         dest = cls.absolute_path(dest_path)
#
#         # Check source exists and is readable
#         if not source.exists():
#             raise FileNotFoundError(f"Source path does not exist: {source_path}")
#
#         if not os.access(source, os.R_OK):
#             raise PermissionError(f"No read permission for source: {source_path}")
#
#         # Check destination doesn't exist
#         if dest.exists():
#             raise FileExistsError(f"Destination already exists: {dest_path}")
#
#         # Check we can write to destination directory
#         dest_parent = dest.parent
#         if dest_parent.exists():
#             if not os.access(dest_parent, os.W_OK):
#                 raise PermissionError(
#                     f"No write permission in destination directory: {dest_parent}"
#                 )
#         else:
#             # Check if we can create the parent directory
#             if not cls._check_can_create_parent(dest_parent):
#                 raise PermissionError(f"Cannot create destination directory: {dest_parent}")
#
#     @classmethod
#     def validate_delete_access(cls, file_path: str | Path) -> None:
#         """
#         Validate that a delete operation can be performed.
#
#         Args:
#             file_path: File or directory path to delete
#
#         Raises:
#             FileNotFoundError: If path doesn't exist
#             PermissionError: If insufficient permissions
#         """
#         path = cls.absolute_path(file_path)
#
#         # Check path exists
#         if not path.exists():
#             raise FileNotFoundError(f"Path does not exist: {file_path}")
#
#         # Check we have write permission in the parent directory
#         if not os.access(path.parent, os.W_OK):
#             raise PermissionError(f"No write permission in directory: {path.parent}")
#
#         # For directories, check they're not read-only and we can delete contents
#         if path.is_dir():
#             if not os.access(path, os.W_OK | os.X_OK):
#                 raise PermissionError(
#                     f"No write/execute permission for directory: {file_path}"
#                 )
#
#     @classmethod
#     def move_file_or_directory(cls, source_path: str | Path, dest_path: str | Path) -> None:
#         """
#         Move a file or directory from source to destination.
#
#         Args:
#             source_path: Source file/directory path
#             dest_path: Destination path
#
#         Raises:
#             Same as validate_move_access, plus shutil.Error for copy failures
#         """
#         source = cls.absolute_path(source_path)
#         dest = cls.absolute_path(dest_path)
#
#         # Create destination parent directory if needed
#         dest.parent.mkdir(parents=True, exist_ok=True)
#
#         # Use shutil.move which handles cross-filesystem moves
#         shutil.move(str(source), str(dest))
#
#     @classmethod
#     def copy_file_or_directory(cls, source_path: str | Path, dest_path: str | Path) -> None:
#         """
#         Copy a file or directory from source to destination.
#
#         Args:
#             source_path: Source file/directory path
#             dest_path: Destination path
#
#         Raises:
#             Same as validate_copy_access, plus shutil.Error for copy failures
#         """
#         source = cls.absolute_path(source_path)
#         dest = cls.absolute_path(dest_path)
#
#         # Create destination parent directory if needed
#         dest.parent.mkdir(parents=True, exist_ok=True)
#
#         # Copy file or directory tree
#         if source.is_file():
#             shutil.copy2(str(source), str(dest))  # copy2 preserves metadata
#         else:
#             shutil.copytree(str(source), str(dest))
#
#     @classmethod
#     def delete_file_or_directory(cls, file_path: str | Path) -> None:
#         """
#         Delete a file or directory.
#
#         Args:
#             file_path: File or directory path to delete
#
#         Raises:
#             Same as validate_delete_access, plus OSError for deletion failures
#         """
#         path = cls.absolute_path(file_path)
#
#         if path.is_file():
#             path.unlink()
#         else:
#             shutil.rmtree(str(path))
#
#
#
#
# # ===== What I really need
#
_SIZE_NOTATIONS = {
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
}

_SIZE_PATTERN = re.compile(r"^\s*(?P<size>\d+(?:\.\d+)?)\s*(?P<unit>\w+)\s*$")


def parse_size_notation_into_bytes(size_notation: int | str) -> int:
    if size_notation is not None:
        if isinstance(size_notation, int):
            return size_notation
        else:
            try:
                return int(size_notation)
            except ValueError:
                try:
                    match_result = _SIZE_PATTERN.match(size_notation)
                    if match_result is None:
                        raise ValueError(f"'{size_notation}' is not a valid disk size")
                    size, unit = match_result.groups()
                    unit = unit.strip().lower()
                    try:
                        return int(float(size) * _SIZE_NOTATIONS[unit])
                    except KeyError:
                        supported = [
                            f"{supported_unit[0].upper()}{supported_unit[1:-1]}{supported_unit[-1].upper()}"
                            for supported_unit in _SIZE_NOTATIONS
                        ]
                        raise ValueError(
                            f"'{unit}' is not a valid disk size unit. Supported: {supported}"
                        ) from None
                except (AttributeError, ValueError):
                    raise ValueError(
                        f"'{size_notation}' is not a valid disk size"
                    ) from None
    return 0  # to be on the safe size, since this is used when checking if a write operation can proceed, assume None = 0


@dataclass
class Metadata:
    owner_name: str
    group_name: str
    path: Path
    size: int
    modified_time: str
    is_directory: bool
    is_readable: bool
    is_writable: bool
    encoding: Literal["text", "base64"] | None = None  # set after reading a file


class Filesystem:
    """
    Core functions

    These are the methods that actually interact with the filesystem, mostly one-liners.
    It's useful to keep them in inner methods that can be mocked or overridden in a MockFilesystem
    Keep in mind these do not perform any path normalization or checks, so if you call fs._read_text(Path("~"))
    it won't give you a proper error
    """

    @staticmethod
    def get_absolute_path(path: str | Path) -> Path:
        """Convert path to absolute path. Using PurePath ensures no real filesystem ops can be done using Path"""
        return Path(path).expanduser().resolve()

    @staticmethod
    def _exists(abs_path: Path) -> bool:
        return abs_path.exists()

    @staticmethod
    def _is_dir(abs_path: Path) -> bool:
        return abs_path.is_dir()

    @staticmethod
    def read_metadata(abs_path: Path) -> Metadata:
        stats = abs_path.stat()
        return Metadata(
            path=abs_path,
            size=stats.st_size,
            modified_time=time.ctime(stats.st_mtime),
            is_directory=abs_path.is_dir(),
            owner_name=pwd.getpwuid(stats.st_uid).pw_name,
            group_name=grp.getgrgid(stats.st_gid).gr_name,
            is_readable=os.access(abs_path, os.R_OK),
            is_writable=os.access(abs_path, os.W_OK),
        )

    @staticmethod
    def _get_listing(abs_path: Path) -> list[Path]:
        return sorted(abs_path.iterdir())

    @staticmethod
    def _read_text(abs_path: Path) -> str:
        return abs_path.read_text()

    @staticmethod
    def _read_bytes(abs_path: Path) -> bytes:
        return abs_path.read_bytes()

    @staticmethod
    def _create_directory(abs_path: Path) -> None:
        abs_path.mkdir()

    @staticmethod
    def _write_text(abs_path: Path, content: str = "", encoding="utf-8") -> None:
        abs_path.write_text(content, encoding=encoding)

    @staticmethod
    def _append_text(abs_path: Path, content: str = "", encoding="utf-8") -> None:
        with open(abs_path, "a", encoding=encoding) as fd:
            fd.write(content)

    @staticmethod
    def _copy_file(abs_src_path: Path, abs_dest_path: Path) -> None:
        shutil.copy2(abs_src_path, abs_dest_path)

    @staticmethod
    def _copy_dir(src_path: Path, dest_path: Path) -> None:
        shutil.copytree(src_path, dest_path)

    @staticmethod
    def _move(src_path: Path, dest_path: Path) -> None:
        shutil.move(src_path, dest_path)

    @staticmethod
    def _get_free_space(abs_path: Path) -> int:
        return shutil.disk_usage(abs_path).free

    @staticmethod
    def _delete_file(abs_path: Path) -> None:
        abs_path.unlink()

    @staticmethod
    def _delete_dir(abs_path: Path) -> None:
        shutil.rmtree(abs_path)

    @staticmethod
    def _is_text_file(abs_path: Path, _blocksize: int = 512) -> bool:
        """
        Believe it or not, the most reliable way to tell if a real file
        is to read a piece of it and find b'\x00'
        """
        with abs_path.open("rb") as fd:
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
        # mime_type = magic.from_file(abs_path, mime=True)
        # return .startswith("text/")

    """Helpers"""

    @classmethod
    def closest_writable_parent(cls, abs_dir_path: Path) -> Path | None:
        """
        Check that a directory can be created by walking up the tree
        until we find an existing directory and checking its permissions.
        """
        while True:
            if cls._exists(abs_dir_path):
                return abs_dir_path if cls.is_writable(abs_dir_path) else None
            # Reached root dir without being writable
            if abs_dir_path == abs_dir_path.parent:
                return None
            abs_dir_path = abs_dir_path.parent

    @classmethod
    def is_readable(cls, abs_path: Path) -> bool:
        try:
            return cls.read_metadata(abs_path).is_readable
        except (PermissionError, OSError):
            # If we can't read metadata, it's not readable
            return False

    @classmethod
    def is_writable(cls, abs_path: Path) -> bool:
        return cls.read_metadata(abs_path).is_writable

    """Validation"""

    @classmethod
    def validate_read_access(cls, file_path: str | Path) -> None:
        """
        Validate that a file can be read.

        Args:
            file_path: Source file path

        Raises:
            FileNotFoundError: If trying to read a non-existing file
            IsADirectoryError: If trying to read a directory
            PermissionError: If file is not readable
        """
        abs_path = cls.get_absolute_path(file_path)
        if not cls._exists(abs_path):
            raise FileNotFoundError(f"Path {abs_path} does not exist")
        # if cls._is_dir(abs_path):
        #     raise IsADirectoryError(f"File {abs_path} is a directory")
        if not cls.is_readable(abs_path):
            raise PermissionError(f"Path {abs_path} is not readable")

    @classmethod
    def validate_delete_access(cls, path: str | Path) -> None:
        """
        Validate that a file or directory can be deleted.

        Args:
            path: Source file/directory path

        Raises:
            FileNotFoundError: If trying to read a non-existing file
            IsADirectoryError: If trying to read a directory
            PermissionError: If file is not readable
        """
        abs_path = cls.get_absolute_path(path)
        if not cls._exists(abs_path):
            raise FileNotFoundError(f"File {abs_path} does not exist")
        if not cls.is_writable(abs_path.parent):
            raise PermissionError(f"File {abs_path.parent} is not writable")

    @classmethod
    def validate_write_access(
        cls,
        path: str | Path,
        content: str | None = None,
        content_size: int | None = None,
        min_disk_size_left: str | int = 0,
    ) -> None:
        """
        Validate that a file or directory can be written.
        Regardless if the path is for a directory or a file, it checks whether that path can be written to its parent.

        Args:
            path: Source file/directory path
            content_size: Optional size to be written (omitted for directories)
            min_disk_size_left: Optional minimum disk space left in bytes after writing

        Raises:
            IsADirectoryError: If trying to overwrite an existing directory
            PermissionError: If parent directory does not exist and cannot be created,
                    or parent directory exists and is not writable
            OSError: If there would not enough disk space left after writing
        """
        abs_path = cls.get_absolute_path(path)
        min_disk_bytes_left = parse_size_notation_into_bytes(min_disk_size_left)

        # Check if path already exists, if it's a directory we cannot overwrite,
        # if it does not exist then we need to check permissions on the parent
        # parent_to_write_into = abs_path.parent
        if cls._exists(abs_path):
            if cls._is_dir(abs_path):
                raise IsADirectoryError(
                    f"Cannot overwrite existing directory {abs_path}"
                )
            elif not cls.is_writable(abs_path):
                raise PermissionError(f"Cannot write into file {abs_path}")
        # If the path does not exist, or it exists and is a file, then we need to find the closest
        # writable parent - so if we have /test/ and we're trying to write /test/dir1/dir2/file1.txt,
        # that would we /test/
        closest_writable_parent = cls.closest_writable_parent(abs_path.parent)
        if not closest_writable_parent:
            raise PermissionError(f"Cannot create parent directory {abs_path.parent}")

        # If the parent directory does not exist, check if it's possible to create it
        # abs_parent = abs_path.parent
        # closest_writable_parent = abs_parent
        # if not cls._exists(abs_parent):
        #     closest_writable_parent = cls.closest_writable_parent(abs_parent)
        #     if not closest_writable_parent:
        #         raise PermissionError(f"Cannot create parent directory {abs_parent}")

        # If the parent directory exists check if it can be written to
        # elif not cls.is_writable(abs_parent):
        #     raise PermissionError(f"Cannot write to parent directory {abs_parent}")

        # Check if there is enough space after writing
        if not content_size and content is not None:
            content_size = len(content.encode("utf-8"))
        if content_size is not None:
            free_space = cls._get_free_space(closest_writable_parent)
            free_after_write = free_space - content_size
            if not free_space - content_size > min_disk_bytes_left:
                raise OSError(
                    f"Insufficient disk space: After writing {content_size} to {abs_path} bytes, only {free_after_write} "
                    f"bytes would be available, minimum configured is {min_disk_bytes_left} bytes"
                )

    """
    File operations

    These are the ones you're supposed to use in the project
    These do checks, validation and accept string and relative/unexpanded paths
    """

    @classmethod
    def read_file(cls, path: str | Path) -> tuple[str, Literal["text", "base64"]]:
        """
        Reads a file.

        Args:
            path: Source file/directory path
        """
        abs_path = cls.get_absolute_path(path)
        cls.validate_read_access(abs_path)
        if cls._is_dir(abs_path):
            raise IsADirectoryError(f"Cannot read directory {abs_path}")
        try:
            if cls._is_text_file(abs_path):
                return (cls._read_text(abs_path), "text")
            else:
                raise Exception("utf-8", None, 0, -1, "Fallback to Base64")
        except Exception:
            return (
                base64.b64encode(cls._read_bytes(abs_path)).decode("utf-8"),
                "base64",
            )

    @classmethod
    def copy(
        cls, src_path: str | Path, dest_path: str | Path, min_space_left: int
    ) -> None:
        src_path = cls.get_absolute_path(src_path)
        dest_path = cls.get_absolute_path(dest_path)

        src_size = cls.read_metadata(src_path).size
        cls.validate_read_access(src_path)
        cls.validate_write_access(
            dest_path, content_size=src_size, min_disk_size_left=min_space_left
        )
        cls.create_directory(dest_path.parent)

        if cls._is_dir(src_path):
            cls._copy_dir(src_path, dest_path)
        else:
            cls._copy_file(src_path, dest_path)

    @classmethod
    def move(cls, src_path: str | Path, dest_path: str | Path) -> None:
        src_path = cls.get_absolute_path(src_path)
        dest_path = cls.get_absolute_path(dest_path)

        cls.validate_read_access(src_path)
        cls.validate_write_access(dest_path)
        cls.create_directory(dest_path.parent)

        cls._move(src_path, dest_path)

    @classmethod
    def delete(cls, path: str | Path) -> None:
        abs_path = cls.get_absolute_path(path)
        cls.validate_delete_access(abs_path)
        if cls._is_dir(abs_path):
            cls._delete_dir(abs_path)
        else:
            cls._delete_file(abs_path)

    @classmethod
    def create_directory(cls, dir_path: str | Path, exist_ok=True) -> None:
        abs_path = cls.get_absolute_path(dir_path)
        if cls._exists(abs_path):
            if exist_ok:
                return
            else:
                raise PermissionError(f"Directory {abs_path} already exists")
        else:
            if not cls._exists(abs_path.parent):
                cls.create_directory(abs_path.parent, exist_ok=True)
            cls._create_directory(abs_path)

    @classmethod
    def write_file(
        cls,
        file_path: str | Path,
        content: str = "",
        encoding: str = "utf-8",
        min_space_left: int = 0,
        append=False,
    ) -> None:
        abs_path = cls.get_absolute_path(file_path)
        size = len(content.encode(encoding))
        cls.validate_write_access(
            abs_path, content_size=size, min_disk_size_left=min_space_left
        )
        cls.create_directory(abs_path.parent, exist_ok=True)
        if append and cls._exists(abs_path):
            cls._append_text(abs_path, content, encoding=encoding)
        else:
            cls._write_text(abs_path, content, encoding=encoding)

    @classmethod
    def get_dir_listing(cls, dir_path: str | Path) -> dict[Path, Metadata]:
        abs_path = cls.get_absolute_path(dir_path)
        cls.validate_read_access(abs_path)
        if not cls._is_dir(abs_path):
            raise NotADirectoryError(f"File {abs_path} is not a directory")
        dir_listing = cls._get_listing(abs_path)
        return {path: cls.read_metadata(path) for path in dir_listing}
