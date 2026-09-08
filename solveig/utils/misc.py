from __future__ import annotations

import re
from datetime import UTC, datetime
from os import PathLike
from typing import Any

import pyperclip
from anyio import Path
from pydantic import ByteSize

from solveig.utils.file import Filesystem


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
    abs_path: str | PathLike,
    is_dir: bool,
    size: int | None = None,
    line_count: int | None = None,
) -> str:
    """One filesystem entry as a display line, home-shortened.

    Takes only the absolute path: what the model typed is a tool's business, not
    something a reader of the line needs to see twice. A `None` size or line count is
    a fact that could not be read, so its segment is omitted rather than guessed at.
    """
    shown = Filesystem.get_simple_path(Path(abs_path))
    path_info = f"{'🗁 ' if is_dir else '🗎'} {shown}"
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


CLI_SETTINGS_OPTS: dict[str, Any] = {
    "cli_exit_on_error": False,
    "cli_kebab_case": False,
    "cli_implicit_flags": True,
    "case_sensitive": True,
    "cli_enforce_required": False,
}


def error_to_text(error: Exception | str) -> str:
    if isinstance(error, Exception):
        return f"{error.__class__.__name__}: {error}"
    return str(error)
