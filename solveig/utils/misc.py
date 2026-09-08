from __future__ import annotations

import re
from datetime import UTC, datetime
from os import PathLike
from typing import Any, Callable, Iterable

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


class ChoicesDict[T](dict[str, T]):
    """
    Behaves like a dict of name-of-thing-to-actual-thing.
    Acts as both resolver for names and available options.
    On missing entries, raises a descriptive exception that is
    aware of available choices instead of a generic KeyError.
    """
    def __init__(
            self,
            init: dict[str, T] | Iterable[str | T] | None = None,
            namer: Callable[[T], str] = str,
            getter: Callable[[str], T] | None = None,
            error_label: str | None = None,
    ):
        super().__init__()
        self._getter = getter
        self._namer = namer
        self._error_label = error_label
        if init is not None:
            if isinstance(init, dict):
                self.update(init)
            else:
                self.add(*init)

    def add(self, *entries: str | T) -> None:
        """
        Utility method that allows adding entries using the namer/getter
        instead of providing the key-value pair
        """
        for entry in entries:
            if isinstance(entry, str):
                if self._getter:
                    self[entry] = self._getter(entry)
                else:
                    raise ValueError(
                        "Getter not set, cannot resolve "
                        f"{self._error_label or "entry"} from '{entry}'."
                    )
            else:
                self[self._namer(entry)] = entry

    def __getitem__(self, name: str) -> T:
        try:
            return super().__getitem__(name)
        except KeyError as error:
            raise ValueError(
                f"No {self._error_label or "entry"} found for '{name}'. "
                f"Use one of {sorted(self.keys())}"
            ) from error
