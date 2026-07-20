from __future__ import annotations

import os

import anyconfig

DEFAULT_CONFIG_SEARCH: list[str] = ["~/.solveig/config", "~/.config/solveig"]
_EXTS: tuple[str, ...] = ("json", "yaml", "yml", "toml")

# Old flat key -> new dotted path. Presence of any at the top level is a hard error.
LEGACY_KEY_MAP: dict[str, str] = {
    "url": "api.url", "api_type": "api.type", "api_key": "api.key",
    "model": "api.model", "temperature": "api.temperature",
    "max_context": "api.max_context", "timeout": "api.timeout",
    "http_timeout": "tools.http.timeout",
    "http_max_response_bytes": "tools.http.max_response_bytes",
    "no_commands": "tools.command.enabled (inverted)",
    "auto_execute_commands": "tools.command.auto_execute",
    "sessions_dir": "session.dir", "auto_save_session": "session.auto_save",
    "theme": "interface.theme", "code_theme": "interface.code_theme",
    "stream": "interface.stream",
    "auto_collapse_tools": "interface.auto_collapse_tools",
    "auto_copy_selection": "interface.auto_copy_selection",
    "mcp_servers": "mcp.servers",
    "verbose": "(removed)",
}


def resolve_config_files(explicit: str | None) -> list[str]:
    """Highest precedence first. Explicit path short-circuits the search."""
    if explicit:
        return [explicit]
    found: list[str] = []
    for base in DEFAULT_CONFIG_SEARCH:
        for ext in _EXTS:
            path = os.path.expanduser(f"{base}.{ext}")
            if os.path.isfile(path):
                found.append(path)
    return found


def _check_legacy(data: dict) -> None:
    legacy = [k for k in data if k in LEGACY_KEY_MAP]
    if legacy:
        lines = "\n".join(f"  - '{k}'  ->  {LEGACY_KEY_MAP[k]}" for k in legacy)
        raise ValueError(
            "This config uses the old flat layout. Keys moved:\n"
            f"{lines}\n"
            "Update your config to the nested schema (see README / CLAUDE.md)."
        )


def load_paths(paths_high_first: list[str]) -> dict:
    """Merge with EARLIER paths winning. anyconfig.load merges a list low->high,
    so reverse (highest goes last => wins)."""
    if not paths_high_first:
        return {}
    merged = anyconfig.load(list(reversed(paths_high_first)), ac_merge=anyconfig.MS_DICTS)
    data = dict(merged) if merged else {}
    _check_legacy(data)
    return data


def save_config(data: dict, path: str) -> None:
    parent = os.path.dirname(os.path.expanduser(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    anyconfig.dump(data, os.path.expanduser(path))
