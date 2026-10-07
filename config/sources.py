from __future__ import annotations

from collections.abc import Sequence
from os import PathLike
from typing import Any, TYPE_CHECKING
import pathlib

import anyconfig
from pydantic import TypeAdapter
from pydantic_settings import PydanticBaseSettingsSource, BaseSettings

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

    def __init__(
            self,
            settings_cls: type[BaseSettings],
            field_name: str = "config_files",
    ):
        super().__init__(settings_cls)
        self._field_name = field_name

    # pydantic base-class override
    def get_field_value(self, field, field_name):
        return None, "", False

    def __call__(self) -> dict[str, Any]:
        field = self.settings_cls.model_fields[self._field_name]

        # `current_state` holds what every higher-priority source produced,
        #  already merged in priority order
        found_paths = self.current_state.get(self._field_name)
        # Non-default paths (code, CLI flags , env vars) are required to exist
        required = found_paths is not None
        if found_paths is None:
            found_paths = field.get_default(call_default_factory=True)

        # Parsed by the field's own type: "a,b" from env or CLI, paths from code
        paths = TypeAdapter(field.rebuild_annotation()).validate_python(found_paths)

        # If paths are required and any is missing/not-a-file, raise
        if required and (missing := [path for path in paths if not path.is_file()]):
            raise FileNotFoundError(
                f"Config file(s) not found: {', '.join(map(str, missing))}"
            )

        read = [path for path in paths if path.is_file()]
        data = load_and_merge_configs(read)
        data[self._field_name] = read
        return data
