from __future__ import annotations

from collections.abc import Sequence
from os import PathLike
from typing import Any
import pathlib

import anyconfig
from pydantic_settings import PydanticBaseSettingsSource


# DEFAULT_CONFIG_SEARCH: list[str] = ["./.solveig/config", "~/.solveig/config"]
EXTENSIONS: tuple[str, ...] = ("json", "yaml", "yml", "toml")


def load_and_merge_configs(paths_low_to_high: Sequence[str | PathLike]) -> dict:
    """Merge multiple config files with higher precedence winning."""
    if not paths_low_to_high:
        return {}
    merged = anyconfig.load(
        [pathlib.Path(path).resolve() for path in paths_low_to_high],
        ac_merge=anyconfig.MS_DICTS,
    )
    return merged if isinstance(merged, dict) else {}


def save_config(data: dict, path: str | PathLike) -> None:
    anyconfig.dump(data, pathlib.Path(path).expanduser().resolve())


class ConfigFileSource(PydanticBaseSettingsSource):
    """A pydantic-settings class modeling one config file passed through `--config FILE`.
    Resolved paths get loaded by pydantic-settings and stored in `config.config_files`."""

    def __init__(self, settings_cls, field_name: str, requested: list[pathlib.Path] | None = None):
        super().__init__(settings_cls)
        self._field_name = field_name
        self._requested = requested or []

    # pydantic base-class override
    def get_field_value(self, field, field_name):
        return None, "", False

    def __call__(self) -> dict[str, Any]:
        resolved = [
            path for path in self._requested
            if path.is_file()
        ]
        # Load the paths, merge the configs, stamp the config_files before returning
        data = load_and_merge_configs(resolved)
        data[self._field_name] = resolved
        return data
