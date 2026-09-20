from __future__ import annotations

from collections.abc import Sequence
from os import PathLike
from typing import Any

import anyconfig
from pydantic_settings import PydanticBaseSettingsSource

from solveig.utils.file import Filesystem, SyncPath


# DEFAULT_CONFIG_SEARCH: list[str] = ["./.solveig/config", "~/.solveig/config"]
EXTENSIONS: tuple[str, ...] = ("json", "yaml", "yml", "toml")


def _for_anyconfig(path: str | PathLike) -> SyncPath:
    """Wraps any path-like in the type anyconfig takes."""
    return SyncPath(path)

def load_and_merge_configs(paths_low_to_high: Sequence[str | PathLike]) -> dict:
    """Merge multiple config files with higher precedence winning."""
    if not paths_low_to_high:
        return {}
    merged = anyconfig.load(
        [_for_anyconfig(path) for path in paths_low_to_high],
        ac_merge=anyconfig.MS_DICTS,
    )
    return merged if isinstance(merged, dict) else {}

# def resolve_config_files(explicit: Sequence[str | PathLike]) -> list[SyncPath]:
#     """Highest precedence first. Any explicit --config FILE (repeatable)
#     replaces the default search entirely — passing configs means we do NOT
#     also merge the search paths. Among explicit files the LAST one wins
#     (and is where /config save writes), so the list comes back reversed.
#     Non-existent explicit paths are dropped (the historical record is argv)."""
#     if explicit:
#         explicit_paths = [
#             _for_anyconfig(Filesystem.get_absolute_path(path))
#             for path in explicit
#         ]
#         return [ path for path in explicit_paths if path.is_file() ]
#
#     found: list[SyncPath] = []
#     for base in DEFAULT_CONFIG_SEARCH:
#         for ext in EXTENSIONS:
#             # Build the config path, remove possible dots on the default and extension
#             path_str = f"{base.rstrip(".")}.{ext.lstrip(".")}"
#             path = _for_anyconfig(Filesystem.get_absolute_path(path_str))
#             if path.is_file():
#                 found.append(path)
#     return found

# def load_paths(paths_high_first: Sequence[str | PathLike]) -> dict:
#     """Merge with HIGHER-precedence paths winning. anyconfig.load merges
#     low→high (last wins), so we reverse (highest goes last)."""
#     if not paths_high_first:
#         return {}
#     low_to_high = [
#         _for_anyconfig(Filesystem.get_absolute_path(path))
#         for path in reversed(paths_high_first)
#     ]
#     merged = anyconfig.load(low_to_high, ac_merge=anyconfig.MS_DICTS)
#     data = dict(merged) if isinstance(merged, dict) else {}
#     # plugins.paths UNIONS across every config file (order-preserving dedupe)
#     # — each layer contributes a discovery dir. Re-reading individual files
#     # here is a second pass; configs are kilobyte-scale so the double-IO is
#     # cheaper than a recursive deep-merge by hand to avoid it.
#     union: list[str] = []
#     for path in low_to_high:
#         one = anyconfig.load(path)
#         if not isinstance(one, dict):
#             continue
#         for pp in (one.get("plugins") or {}).get("paths") or []:
#             if pp not in union:
#                 union.append(pp)
#     if union:
#         data.setdefault("plugins", {})["paths"] = union
#     return data


def save_config(data: dict, path: str | PathLike) -> None:
    abs_path = Filesystem.get_absolute_path(path)
    anyconfig.dump(data, _for_anyconfig(abs_path))


class ConfigFileSource(PydanticBaseSettingsSource):
    """A pydantic-settings class modeling one config file passed through `--config FILE`.
    Resolved paths get loaded by pydantic-settings and stored in `config.config_files`."""

    def __init__(self, settings_cls, field_name: str, requested: list[str] | None = None):
        super().__init__(settings_cls)
        self._field_name = field_name
        self._requested = requested or []

    # pydantic base-class override
    def get_field_value(self, field, field_name):
        return None, "", False

    def __call__(self) -> dict[str, Any]:
        resolved = [
            pure_path
            for path in self._requested
            if (pure_path := _for_anyconfig(Filesystem.get_absolute_path(path))).is_file()
        ]
        # Load the paths, merge the configs, stamp the config_files before returning
        data = load_and_merge_configs(resolved)
        data[self._field_name] = resolved
        return data
