import re
from datetime import UTC, datetime
from os import PathLike
from typing import TYPE_CHECKING

import pyperclip
from pydantic import ByteSize

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
        path_info += f"  |  ⛁ {ByteSize(size).human_readable()}"
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
