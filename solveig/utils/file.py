import asyncio
import base64
import grp
import os
import pwd
import shutil
from dataclasses import dataclass
from os import PathLike
from pathlib import Path as SyncPath
from pathlib import PurePath
from typing import Literal

from anyio import Path
from pydantic import Field

from solveig.utils.misc import parse_human_readable_size


@dataclass
class Metadata:
    owner_name: str
    group_name: str
    path: str
    size: int
    is_directory: bool
    is_readable: bool
    is_writable: bool
    modified_time: int = Field(
        ...,
        description="Last modified time for file or dir as UNIX timestamp",
    )
    encoding: Literal["text", "base64"] | None = None  # set after reading a file
    listing: dict[str, "Metadata"] | None = None


@dataclass
class FileContent:
    content: str | bytes
    encoding: Literal["text", "base64"]


class Filesystem:
    """
    Async filesystem operations using AnyIO hybrid approach:
    - AnyIO for common operations (read, write, stat, exists, etc.)
    - asyncio.to_thread only for missing shutil operations (copy2, copytree, move, rmtree)
    """

    # =============================================================================
    # PRIVATE - Low-level async filesystem operations
    # =============================================================================

    @staticmethod
    async def _get_listing(abs_path: Path) -> list[Path]:
        """Async directory listing using AnyIO."""
        items = []
        async for item in abs_path.iterdir():
            items.append(item)
        return sorted(items)

    @staticmethod
    async def _read_text(abs_path: Path) -> str:
        """Async text file reading using AnyIO."""
        return await abs_path.read_text()

    @staticmethod
    async def _read_bytes(abs_path: Path) -> bytes:
        """Async binary file reading using AnyIO."""
        return await abs_path.read_bytes()

    @staticmethod
    async def _create_directory(abs_path: Path) -> None:
        """Async directory creation using AnyIO."""
        await abs_path.mkdir()

    @staticmethod
    async def _write_text(abs_path: Path, content: str = "", encoding="utf-8") -> None:
        """Async text file writing using AnyIO."""
        await abs_path.write_text(content, encoding=encoding)

    @staticmethod
    async def _append_text(abs_path: Path, content: str = "", encoding="utf-8") -> None:
        """Async text file appending using AnyIO."""
        # AnyIO doesn't have append mode, so we read + write
        try:
            existing = await abs_path.read_text(encoding=encoding)
            await abs_path.write_text(existing + content, encoding=encoding)
        except FileNotFoundError:
            await abs_path.write_text(content, encoding=encoding)

    @staticmethod
    async def _copy_file(abs_src_path: Path, abs_dest_path: Path) -> None:
        """Async file copying - use shutil.copy2 for metadata preservation."""
        await asyncio.to_thread(
            shutil.copy2, PurePath(abs_src_path), PurePath(abs_dest_path)
        )

    @staticmethod
    async def _copy_dir(src_path: Path, dest_path: Path) -> None:
        """Async directory copying - use shutil.copytree."""
        await asyncio.to_thread(
            shutil.copytree, PurePath(src_path), PurePath(dest_path)
        )

    @staticmethod
    async def _move(src_path: Path, dest_path: Path) -> None:
        """Async file/directory moving - use shutil.move."""
        await asyncio.to_thread(shutil.move, PurePath(src_path), PurePath(dest_path))

    @staticmethod
    async def _get_free_space(abs_path: Path) -> int:
        """Async disk space checking - use shutil.disk_usage."""
        return await asyncio.to_thread(
            lambda: shutil.disk_usage(PurePath(abs_path)).free
        )

    @staticmethod
    async def _delete_file(abs_path: Path) -> None:
        """Async file deletion using AnyIO."""
        await abs_path.unlink()

    @staticmethod
    async def _delete_dir(abs_path: Path) -> None:
        """Async directory deletion - use shutil.rmtree."""
        await asyncio.to_thread(shutil.rmtree, PurePath(abs_path))

    @staticmethod
    async def _is_text_file(abs_path: Path, _blocksize: int = 512) -> bool:
        """Async text file detection using AnyIO."""
        chunk = await abs_path.read_bytes()
        chunk = chunk[:_blocksize]  # Limit to blocksize
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
    async def _closest_writable_parent(cls, abs_dir_path: Path) -> Path | None:
        """Async check for closest writable parent directory."""
        while True:
            if await cls.exists(abs_dir_path):
                return abs_dir_path if await cls.is_writable(abs_dir_path) else None
            # Reached root dir without being writable
            if abs_dir_path == abs_dir_path.parent:
                return None
            abs_dir_path = abs_dir_path.parent

    # =============================================================================
    # VALIDATION - Access and permission checking
    # =============================================================================

    @classmethod
    async def validate_read_access(cls, file_path: str | Path) -> None:
        """Async validation that a file can be read."""
        abs_path = cls.get_absolute_path(file_path)
        if not await cls.exists(abs_path):
            raise FileNotFoundError(f"Path {abs_path} does not exist")
        if not await cls.is_readable(abs_path):
            raise PermissionError(f"Path {abs_path} is not readable")

    @classmethod
    async def validate_delete_access(cls, path: str | Path) -> None:
        """Async validation that a file or directory can be deleted."""
        abs_path = cls.get_absolute_path(path)
        if not await cls.exists(abs_path):
            raise FileNotFoundError(f"File {abs_path} does not exist")
        if not await cls.is_writable(abs_path.parent):
            raise PermissionError(f"File {abs_path.parent} is not writable")

    @classmethod
    async def validate_write_access(
        cls,
        path: str | Path,
        content: str | bytes | None = None,
        content_size: int | None = None,
        min_disk_size_left: str | int = 0,
    ) -> None:
        """Async validation that a file or directory can be written."""
        abs_path = cls.get_absolute_path(path)
        min_disk_bytes_left = parse_human_readable_size(min_disk_size_left)

        # Check if path already exists
        if await cls.exists(abs_path):
            if await cls.is_dir(abs_path):
                raise IsADirectoryError(
                    f"Cannot overwrite existing directory {abs_path}"
                )
            elif not await cls.is_writable(abs_path):
                raise PermissionError(f"Cannot write into file {abs_path}")

        # Find the closest writable parent for new files/directories
        closest_writable_parent = await cls._closest_writable_parent(abs_path.parent)
        if not closest_writable_parent:
            raise PermissionError(f"Cannot create parent directory {abs_path.parent}")

        # Check disk space
        if not content_size and content is not None:
            content_size = len(
                content.encode("utf-8") if isinstance(content, str) else content
            )
        if content_size is not None:
            free_space = await cls._get_free_space(closest_writable_parent)
            free_after_write = free_space - content_size
            if free_after_write <= min_disk_bytes_left:
                raise OSError(
                    f"Insufficient disk space: After writing {content_size} bytes to {abs_path}, "
                    f"only {free_after_write} bytes would be available, minimum configured is {min_disk_bytes_left} bytes"
                )

    # =============================================================================
    # OPERATIONS - Public async API for file/directory operations
    # =============================================================================

    @staticmethod
    def get_absolute_path(path: str | PathLike) -> Path:
        """Convert path to absolute path with user expansion (sync operation)."""
        return Path(SyncPath(path).expanduser().resolve())

    @staticmethod
    async def exists(abs_path: Path) -> bool:
        """Async check if path exists using AnyIO."""
        return await abs_path.exists()

    @staticmethod
    async def is_dir(abs_path: Path) -> bool:
        """Async check if path is a directory using AnyIO."""
        return await abs_path.is_dir()

    @classmethod
    async def is_readable(cls, abs_path: Path) -> bool:
        """Async check if path is readable."""
        try:
            metadata = await cls.read_metadata(abs_path, descend_level=0)
            return metadata.is_readable
        except (PermissionError, OSError):
            return False

    @classmethod
    async def is_writable(cls, abs_path: Path) -> bool:
        """Async check if path is writable."""
        try:
            metadata = await cls.read_metadata(abs_path, descend_level=0)
            return metadata.is_writable
        except (PermissionError, OSError):
            return False

    @classmethod
    async def read_metadata(cls, abs_path: Path, descend_level=1) -> Metadata:
        """Async read metadata and dir structure from filesystem using AnyIO."""
        # Use AnyIO for stat operations
        stats = await abs_path.stat()
        is_dir = await cls.is_dir(abs_path)

        if is_dir and descend_level != 0:
            # Get directory listing and recursively read metadata
            sub_paths = await cls._get_listing(abs_path)
            listing = {}

            # Process subdirectories/files in parallel
            tasks = []
            for sub_path in sub_paths:
                abs_sub_path = cls.get_absolute_path(sub_path)
                task = cls.read_metadata(abs_sub_path, descend_level=descend_level - 1)
                tasks.append((abs_sub_path, task))

            # Wait for all metadata reads to complete
            for abs_sub_path, task in tasks:
                listing[str(abs_sub_path)] = await task
        else:
            listing = None

        # Get owner/group info (still need to_thread for these)
        def _get_user_info():
            return (
                pwd.getpwuid(stats.st_uid).pw_name,
                grp.getgrgid(stats.st_gid).gr_name,
                os.access(abs_path, os.R_OK),
                os.access(abs_path, os.W_OK),
            )

        owner_name, group_name, is_readable, is_writable = await asyncio.to_thread(
            _get_user_info
        )

        return Metadata(
            path=str(abs_path),
            size=stats.st_size,
            modified_time=int(stats.st_mtime),
            is_directory=is_dir,
            owner_name=owner_name,
            group_name=group_name,
            is_readable=is_readable,
            is_writable=is_writable,
            listing=listing,
        )

    @classmethod
    async def read_file(cls, path: Path) -> FileContent:
        """Async read file contents with automatic text/binary detection."""
        abs_path = cls.get_absolute_path(path)
        await cls.validate_read_access(abs_path)
        if await cls.is_dir(abs_path):
            raise IsADirectoryError(f"Cannot read directory {abs_path}")

        try:
            if await cls._is_text_file(abs_path):
                content = await cls._read_text(abs_path)
                return FileContent(content=content, encoding="text")
            else:
                raise Exception("utf-8", None, 0, -1, "Fallback to Base64")
        except Exception:
            binary_content = await cls._read_bytes(abs_path)
            content = base64.b64encode(binary_content).decode("utf-8")
            return FileContent(content=content, encoding="base64")

    @classmethod
    async def write_file(
        cls,
        file_path: Path,
        content: str = "",
        encoding: str = "utf-8",
        min_space_left: int = 0,
        append=False,
    ) -> None:
        """Async write content to file with validation and parent directory creation."""
        abs_path = cls.get_absolute_path(file_path)
        size = len(content.encode(encoding))
        await cls.validate_write_access(
            abs_path, content_size=size, min_disk_size_left=min_space_left
        )
        await cls.create_directory(abs_path.parent, exist_ok=True)

        if append and await cls.exists(abs_path):
            await cls._append_text(abs_path, content, encoding=encoding)
        else:
            await cls._write_text(abs_path, content, encoding=encoding)

    @classmethod
    async def create_directory(cls, dir_path: Path, exist_ok=True) -> None:
        """Async create directory with recursive parent creation."""
        abs_path = cls.get_absolute_path(dir_path)
        if await cls.exists(abs_path):
            if exist_ok:
                return
            else:
                raise PermissionError(f"Directory {abs_path} already exists")
        else:
            # Recursively create parent directories
            if abs_path != abs_path.parent and not await cls.exists(abs_path.parent):
                await cls.create_directory(abs_path.parent, exist_ok=True)
            await cls._create_directory(abs_path)

    @classmethod
    async def copy(cls, src_path: Path, dest_path: Path, min_space_left: int) -> None:
        """Async copy file or directory with validation."""
        src_path = cls.get_absolute_path(src_path)
        dest_path = cls.get_absolute_path(dest_path)

        src_metadata = await cls.read_metadata(src_path, descend_level=0)
        src_size = src_metadata.size
        await cls.validate_read_access(src_path)
        await cls.validate_write_access(
            dest_path, content_size=src_size, min_disk_size_left=min_space_left
        )
        await cls.create_directory(dest_path.parent)

        if await cls.is_dir(src_path):
            await cls._copy_dir(src_path, dest_path)
        else:
            await cls._copy_file(src_path, dest_path)

    @classmethod
    async def move(cls, src_path: Path, dest_path: Path) -> None:
        """Async move file or directory with validation."""
        src_path = cls.get_absolute_path(src_path)
        dest_path = cls.get_absolute_path(dest_path)

        await cls.validate_read_access(src_path)
        await cls.validate_write_access(dest_path)
        await cls.create_directory(dest_path.parent)

        await cls._move(src_path, dest_path)

    @classmethod
    async def delete(cls, path: Path) -> None:
        """Async delete file or directory with validation."""
        abs_path = cls.get_absolute_path(path)
        await cls.validate_delete_access(abs_path)
        if await cls.is_dir(abs_path):
            await cls._delete_dir(abs_path)
        else:
            await cls._delete_file(abs_path)

    @classmethod
    def path_matches_patterns(cls, abs_path: Path, patterns: list[Path]) -> bool:
        """Check if a file path matches any of the given glob patterns (sync operation)."""
        return any(abs_path.match(str(pattern)) for pattern in patterns)
