from __future__ import annotations

from collections.abc import Sequence
from os import PathLike

import anyconfig

from solveig.utils.dotted import to_leaves
from solveig.utils.file import Filesystem, SyncPath

DEFAULT_CONFIG_SEARCH: list[str] = ["./.solveig/config", "~/.solveig/config"]
_EXTS: tuple[str, ...] = ("json", "yaml", "yml", "toml")

# Old key -> where it lives now. Either side may be dotted: the check runs over
# the loaded config's leaf paths, so a key that MOVED BETWEEN SECTIONS is caught
# the same way a pre-nesting flat key is. Presence of any is a hard error.
LEGACY_KEY_MAP: dict[str, str] = {
    "url": "api.url",
    "api_type": "api.type",
    "api_key": "api.key",
    "model": "api.model",
    "temperature": "api.temperature",
    "max_context": "api.max_context",
    "timeout": "api.timeout",
    "http_timeout": "tools.http.timeout",
    "http_max_response_bytes": "tools.http.maximum_response_size",
    "no_commands": "tools.command.enabled (inverted)",
    "auto_execute_commands": "tools.command.auto_execute",
    "sessions_dir": "session.path",
    "auto_save_session": "session.auto_save",
    "theme": "interface.tui.theme",
    "code_theme": "interface.tui.code_theme",
    "auto_collapse_tools": "interface.tui.auto_collapse",
    "auto_copy_selection": "interface.tui.auto_copy_selection",
    "interface.theme": "interface.tui.theme",
    "interface.code_theme": "interface.tui.code_theme",
    "interface.auto_copy_selection": "interface.tui.auto_copy_selection",
    "interface.auto_collapse": "interface.tui.auto_collapse",
    "interface.stream": "stream",
    "mcp_servers": "mcp.servers",
    "ignore_paths": "ignored_paths",
    "verbose": "(removed)",
}


def _for_anyconfig(path: str | PathLike) -> SyncPath:
    """Wraps any path-like in the type anyconfig takes."""
    return SyncPath(path)


def resolve_config_files(explicit: Sequence[str | PathLike]) -> list[SyncPath]:
    """Highest precedence first. Any explicit --config FILE (repeatable)
    replaces the default search entirely — passing configs means we do NOT
    also merge the search paths. Among explicit files the LAST one wins
    (and is where /config save writes), so the list comes back reversed.
    Non-existent explicit paths are dropped (the historical record is argv)."""
    if explicit:
        explicit_paths = [
            _for_anyconfig(Filesystem.get_absolute_path(path))
            for path in explicit
        ]
        return [ path for path in explicit_paths if path.is_file() ]

    found: list[SyncPath] = []
    for base in DEFAULT_CONFIG_SEARCH:
        for ext in _EXTS:
            # Build the config path, remove possible dots on the default and extension
            path_str = f"{base.rstrip(".")}.{ext.lstrip(".")}"
            path = _for_anyconfig(Filesystem.get_absolute_path(path_str))
            if path.is_file():
                found.append(path)
    return found


def _check_legacy(data: dict) -> None:
    # Top-level keys AND leaf paths: a flat pre-nesting key is a leaf of its
    # own, and a key that moved between sections is only visible as a path.
    present = to_leaves(data) | set(data)
    legacy = sorted(present & LEGACY_KEY_MAP.keys())
    if legacy:
        lines = "\n".join(f"  - '{k}'  ->  {LEGACY_KEY_MAP[k]}" for k in legacy)
        raise ValueError(
            "This config uses the old flat layout. Keys moved:\n"
            f"{lines}\n"
            "Update your config to the nested schema (see README / CLAUDE.md)."
        )


def load_paths(paths_high_first: Sequence[str | PathLike]) -> dict:
    """Merge with HIGHER-precedence paths winning. anyconfig.load merges
    low→high (last wins), so we reverse (highest goes last)."""
    if not paths_high_first:
        return {}
    low_to_high = [
        _for_anyconfig(Filesystem.get_absolute_path(path))
        for path in reversed(paths_high_first)
    ]
    merged = anyconfig.load(low_to_high, ac_merge=anyconfig.MS_DICTS)
    data = dict(merged) if isinstance(merged, dict) else {}
    _check_legacy(data)
    # plugins.paths UNIONS across every config file (order-preserving dedupe)
    # — each layer contributes a discovery dir. Re-reading individual files
    # here is a second pass; configs are kilobyte-scale so the double-IO is
    # cheaper than a recursive deep-merge by hand to avoid it.
    union: list[str] = []
    for path in low_to_high:
        one = anyconfig.load(path)
        if not isinstance(one, dict):
            continue
        for pp in (one.get("plugins") or {}).get("paths") or []:
            if pp not in union:
                union.append(pp)
    if union:
        data.setdefault("plugins", {})["paths"] = union
    return data


def save_config(data: dict, path: str | PathLike) -> None:
    abs_path = Filesystem.get_absolute_path(path)
    anyconfig.dump(data, _for_anyconfig(abs_path))
