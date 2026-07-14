import re
from datetime import UTC, datetime
from os import PathLike
from typing import TYPE_CHECKING

import pyperclip

if TYPE_CHECKING:
    from anyio import Path


def format_age(mtime: int) -> str:
    """Convert a unix timestamp to a human-readable age string (e.g. '2 hours ago')."""
    delta = max(0, int(datetime.now(UTC).timestamp()) - mtime)
    if delta < 60:
        return "just now"
    if delta < 3600:
        m = delta // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if delta < 86400:
        h = delta // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = delta // 86400
    return f"{d} day{'s' if d != 1 else ''} ago"


SIZE_NOTATIONS = {
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
}

SIZE_PATTERN = re.compile(r"^\s*(?P<size>\d+(?:\.\d+)?)\s*(?P<unit>\w+)\s*$")


def default_json_serialize(o):
    """
    I use Path a lot on this project and can't be hot-fixing every instance to convert to str, this does it automatically
    json.dumps(model, default=default_json_serialize)
    """
    if isinstance(o, PathLike) or isinstance(o, re.Pattern):
        return str(o)
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")


def convert_size_to_human_readable(num_bytes: int, decimal=False) -> str:
    """
    Convert a size in bytes into a human-readable string.

    decimal=True  -> SI units (kB, MB, GB, ...) base 1000
    decimal=False -> IEC units (KiB, MiB, GiB, ...) base 1024
    """
    if decimal:
        step = 1000.0
        units = ["B", "kB", "MB", "GB", "TB", "PB", "EB"]
    else:
        step = 1024.0
        units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"]

    size: float = float(num_bytes)
    for unit in units:
        if size < step:
            return f"{size:.1f} {unit}"
        size /= step
    return f"{size:.1f} {units[-1]}"


def parse_human_readable_size(size_notation: int | str) -> int:
    """
    Converts a size from human notation into number of bytes.

    :param size_notation: Examples: 1MiB, 20 kb, 6 TB
    :return: an integer representing the equivalent number of bytes
    """
    if size_notation is not None:
        if isinstance(size_notation, int):
            return size_notation
        else:
            try:
                return int(size_notation)
            except ValueError:
                try:
                    match_result = SIZE_PATTERN.match(size_notation)
                    if match_result is None:
                        raise ValueError(f"'{size_notation}' is not a valid disk size")
                    size, unit = match_result.groups()
                    unit = unit.strip().lower()
                    try:
                        return int(float(size) * SIZE_NOTATIONS[unit])
                    except KeyError:
                        supported = [
                            f"{supported_unit[0].upper()}{supported_unit[1:-1]}{supported_unit[-1].upper()}"
                            for supported_unit in SIZE_NOTATIONS
                        ]
                        raise ValueError(
                            f"'{unit}' is not a valid disk size unit. Supported: {supported}"
                        ) from None
                except (AttributeError, ValueError):
                    raise ValueError(
                        f"'{size_notation}' is not a valid disk size"
                    ) from None
    return 0  # to be on the safe size, since this is used when checking if a write operation can proceed, assume None = 0


def format_path_info(
    path: str | PathLike,
    abs_path: "Path",
    is_dir: bool,
    size: int | None = None,
    line_count: int | None = None,
) -> str:
    """Format a filesystem path into a single display line with optional metadata."""
    path_info = f"{'🗁 ' if is_dir else '🗎'} {path}"
    if str(abs_path) != str(path):
        path_info += f"  ({abs_path})"
    if size is not None:
        path_info += f"  |  ⛁ {convert_size_to_human_readable(size)}"
    if line_count is not None:
        path_info += f"  |  ☰ {line_count} lines"
    return path_info


FILE_EXTENSION_TO_LANGUAGE = {
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "jsx": "jsx",
    "tsx": "tsx",
    "java": "java",
    "c": "c",
    "cpp": "cpp",
    "cc": "cpp",
    "cxx": "cpp",
    "h": "c",
    "hpp": "cpp",
    "rs": "rust",
    "go": "go",
    "rb": "ruby",
    "php": "php",
    "sh": "bash",
    "bash": "bash",
    "zsh": "zsh",
    "fish": "fish",
    "html": "html",
    "css": "css",
    "scss": "scss",
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "xml": "xml",
    "sql": "sql",
    "md": "markdown",
    "dockerfile": "dockerfile",
}


def get_language(language_sig):
    """

    :param language_sig: language name or extension
    :return: formal language name
    """
    try:
        return FILE_EXTENSION_TO_LANGUAGE[language_sig]
    except KeyError:
        if language_sig in FILE_EXTENSION_TO_LANGUAGE.values():
            return language_sig
        return None


def copy_to_clipboard(text: str) -> None:
    """Copy text to the OS clipboard."""
    pyperclip.copy(text)


def validate_non_empty_path(path: str) -> str:
    """Validate and clean a path string - used by all path-based tools."""
    try:
        path = path.strip()
        if not path:
            raise ValueError("Empty path")
    except (ValueError, AttributeError) as e:
        raise ValueError("Empty path") from e
    return path


def _camel_to_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
