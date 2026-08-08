from __future__ import annotations

import os

import anyconfig

from solveig.utils.dotted import to_leaves

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
    "http_max_response_bytes": "tools.http.max_response_bytes",
    "no_commands": "tools.command.enabled (inverted)",
    "auto_execute_commands": "tools.command.auto_execute",
    "sessions_dir": "session.dir",
    "auto_save_session": "session.auto_save",
    "theme": "interface.tui.theme",
    "code_theme": "interface.tui.code_theme",
    "auto_collapse_tools": "interface.auto_collapse_tools",
    "auto_copy_selection": "interface.tui.auto_copy_selection",
    "interface.theme": "interface.tui.theme",
    "interface.code_theme": "interface.tui.code_theme",
    "interface.auto_copy_selection": "interface.tui.auto_copy_selection",
    "interface.stream": "stream",
    "mcp_servers": "mcp.servers",
    "ignore_paths": "ignored_paths",
    "verbose": "(removed)",
}


def resolve_config_files(explicit: list[str]) -> list[str]:
    """Highest precedence first. Any explicit --config FILE (repeatable)
    replaces the default search entirely — passing configs means we do NOT
    also merge the search paths. Among explicit files the LAST one wins
    (and is where /config save writes), so the list comes back reversed.
    Non-existent explicit paths are dropped (the historical record is argv)."""
    if explicit:
        return [
            p
            for p in (os.path.expanduser(x) for x in reversed(explicit))
            if os.path.isfile(p)
        ]
    found: list[str] = []
    for base in DEFAULT_CONFIG_SEARCH:
        for ext in _EXTS:
            path = os.path.expanduser(f"{base}.{ext}")
            if os.path.isfile(path):
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


def load_paths(paths_high_first: list[str]) -> dict:
    """Merge with HIGHER-precedence paths winning. anyconfig.load merges
    low→high (last wins), so we reverse (highest goes last)."""
    if not paths_high_first:
        return {}
    low_to_high = list(reversed(paths_high_first))
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


def save_config(data: dict, path: str) -> None:
    parent = os.path.dirname(os.path.expanduser(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    anyconfig.dump(data, os.path.expanduser(path))
