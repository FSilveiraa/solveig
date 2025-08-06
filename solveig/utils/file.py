import base64
import grp
import mimetypes
import os
import pwd
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple

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


def parse_size_notation_into_bytes(size_notation: Optional[int | str]) -> int:
    if size_notation is not None:
        if not isinstance(size_notation, int):
            try:
                return int(size_notation)
            except ValueError:
                try:
                    size, unit = _SIZE_PATTERN.match(size_notation).groups()
                    unit = unit.strip().lower()
                    return int(float(size) * _SIZE_NOTATIONS[unit])
                except KeyError:
                    supported = [
                        f"{supported_unit[0].upper()}{supported_unit[1:-1]}{supported_unit[-1].upper()}"
                        for supported_unit in _SIZE_NOTATIONS
                    ]
                    raise ValueError(
                        f"'{unit}' is not a valid disk size unit. Supported: {supported}"
                    )
                except (AttributeError, ValueError):
                    raise ValueError(f"'{size_notation}' is not a valid disk size")
    return 0  # to be on the safe size, since this is used when checking if a write operation can proceed, assume None = 0


def read_metadata_and_entries(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} does not exist")

    stats = os.stat(path)
    is_dir = os.path.isdir(path)
    # resolve uid/gid to names
    owner_name = pwd.getpwuid(stats.st_uid).pw_name
    group_name = grp.getgrgid(stats.st_gid).gr_name

    metadata = {
        "path": os.path.abspath(path),
        "size": stats.st_size,
        "mtime": time.ctime(stats.st_mtime),
        "is_directory": is_dir,
        "owner": owner_name,
        "group": group_name,
    }
    entries = None

    if is_dir:
        # For a directory, list entries (including hidden)
        entries = []
        for name in sorted(os.listdir(path)):
            entry_path = os.path.join(path, name)
            entry_stats = os.stat(entry_path)
            entries.append(
                {
                    "name": name,
                    "is_dir": os.path.isdir(entry_path),
                    "size": entry_stats.st_size,
                    "mtime": time.ctime(entry_stats.st_mtime),
                }
            )
    return metadata, entries


def read_file_as_base64(path: str | Path) -> str:
    with open(path, "rb") as fd:
        return base64.b64encode(fd.read()).decode("utf-8")


def read_file_as_text(path: str | Path) -> str:
    with open(path) as fd:
        return fd.read()


def read_file(path: str | Path) -> Tuple[str, Literal["text", "base64"]]:
    mime, _ = mimetypes.guess_type(path)
    try:
        if mime and mime.startswith("text"):
            return (read_file_as_text(path), "text")
        else:
            raise UnicodeDecodeError("Fallback")
    except (UnicodeDecodeError, Exception):
        return (read_file_as_base64(path), "base64")


def validate_read_access(file_path: str | Path) -> None:
    """
    Validate that a file/directory can be read.
    Raises appropriate exceptions if validation fails.
    """
    abs_path = Path(file_path).expanduser().resolve()

    if not abs_path.exists():
        raise FileNotFoundError("This path doesn't exist")

    if not os.access(abs_path, os.R_OK):
        raise PermissionError(f"Permission denied: Cannot read '{abs_path}'")


def read_file_with_metadata(
    file_path: str | Path, include_content: bool = False
) -> Dict[str, Any]:
    """
    Read file/directory metadata and optionally content.
    Returns dict with 'metadata', 'content', 'encoding', 'directory_listing' keys.
    Raises exceptions on errors - caller handles error wrapping.
    """
    abs_path = Path(file_path).expanduser().resolve()
    is_dir = abs_path.is_dir()

    result = {
        "metadata": None,
        "content": None,
        "encoding": None,
        "directory_listing": None,
    }

    if is_dir:
        metadata, entries = read_metadata_and_entries(abs_path)
        result["metadata"] = metadata
        result["directory_listing"] = entries
    else:
        metadata, _ = read_metadata_and_entries(abs_path)
        result["metadata"] = metadata

        if include_content:
            content, encoding = read_file(abs_path)
            result["content"] = content
            result["encoding"] = encoding

    return result


def validate_write_access(
    file_path: str | Path,
    is_directory: bool = False,
    content: Optional[str] = None,
    min_disk_size_left: Optional[str | int] = None,
) -> None:
    """
    Validate write operation before attempting it.
    Raises appropriate exceptions if validation fails.
    """
    abs_path = Path(file_path).expanduser().resolve()
    min_disk_bytes_left = parse_size_notation_into_bytes(min_disk_size_left)

    # Check if path already exists
    if abs_path.exists():
        if is_directory:
            raise FileExistsError("This directory already exists")
        # For files, we might want to allow overwriting - let caller decide

    # Validate parent directory for both files and directories
    parent_dir = abs_path.parent if not is_directory else abs_path.parent

    # Check parent directory exists and is writable
    if not parent_dir.exists():
        # Parent will be created, check if we can create it
        if not _check_can_create_parent(parent_dir):
            raise PermissionError(
                f"Cannot create parent directory '{parent_dir}': permission denied"
            )
    else:
        # Parent exists, check if we can write to it
        if not os.access(parent_dir, os.W_OK):
            raise PermissionError(
                f"Permission denied: Cannot write to directory '{parent_dir}'"
            )

    # Check available disk space for file writes
    if not is_directory and content:
        try:
            content_size = len(content.encode("utf-8"))
            available_space = shutil.disk_usage(parent_dir).free
            # Require at least 2x the content size for safety
            available_after_write = available_space - content_size
            if available_after_write < min_disk_bytes_left:
                raise OSError(
                    f"Insufficient disk space: After writing {content_size} bytes, only {available_after_write} bytes would be available, minimum configured is {min_disk_bytes_left} bytes"
                )
        except OSError as e:
            raise OSError(f"Cannot check disk space: {e}")


def write_file_or_directory(
    file_path: str | Path, is_directory: bool = False, content: str = ""
) -> None:
    """
    Write a file or create a directory.
    Raises exceptions on errors - caller handles error wrapping.
    """
    abs_path = Path(file_path).expanduser().resolve()

    if is_directory:
        # Create directory
        abs_path.mkdir(parents=True, exist_ok=False)
    else:
        # Ensure parent directory exists
        if not abs_path.parent.exists():
            abs_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file content
        abs_path.write_text(content, encoding="utf-8")


def _check_can_create_parent(parent_dir: Path) -> bool:
    """
    Check if we can create a parent directory by walking up the tree
    until we find an existing directory and checking its permissions.
    """
    current = parent_dir
    while current != current.parent:  # Stop at root
        if current.exists():
            return os.access(current, os.W_OK)
        current = current.parent
    return False  # Reached root without finding writable directory
