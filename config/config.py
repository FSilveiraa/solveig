import sys
from typing import override

from pydantic import Field
from pydantic_settings import BaseSettings, CliSettingsSource

from .annotations import AbsolutePath, CommaSeparated
from .meta import ConfigDict
from .section.static import ConfigSection
from .sources import ConfigFileSource


class Config(BaseSettings, ConfigSection):
    model_config = ConfigDict(
        cli_avoid_json=True,
        cli_exit_on_error=False,
        cli_kebab_case=True,
        cli_implicit_flags=True,
        cli_enforce_required=False,
        default_config_files=[],
    )

    # Whether to read `sys.argv`. An internal switch, never saved or edited
    parse_cli: bool = Field(default=True, exclude=True)
    # Config file paths read, sorted lowest -> highest priority.
    # Add flags and defaults for this field using:
    #  `ConfigDict(cli_shortcuts={"config_files":["c", "config"]}, default_config_files=["~/config.json"])`
    config_files: CommaSeparated[AbsolutePath] = Field(
        default_factory=list, exclude=True
    )

    @override
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """Build the settings-source stack. CLI args flow through `cli_parse_args`;
        `--config` flags are split out for ConfigFileSource."""
        # Parse CLI args list. If `parse_cli` is absent from init_kwargs,
        # then it wasn't passed, use field default
        parse_cli: bool | None = init_settings.init_kwargs.get("parse_cli")
        if parse_cli is None:
            parse_cli = settings_cls.model_fields["parse_cli"].get_default()
        argv = sys.argv[1:] if parse_cli else []

        # A key must match the flag name pydantic-settings generated for the field,
        #  which `cli_kebab_case` makes kebab-case: `max_context` -> `max-context`,
        #  a nested field -> `api.max-context`. Values are used verbatim, with no
        #  case conversion, and a one-character value gets a single dash. Expected:
        #  {"path.to.my-section": ["my-section", "m"]}
        #  Creates: `--my-section` and `-m`
        # Shortcuts from `model_config` (for inherited fields), then from each
        #  field's own `CliFlags`. A value may be one flag or a list of them.
        shortcuts: dict[str, list[str]] = {}
        for path, flags in (cls.model_config.get("cli_shortcuts") or {}).items():
            shortcuts[path.replace("_", "-")] = (
                [flags] if isinstance(flags, str) else list(flags)
            )
        for path, all_cli_flags in cls._cli_flags_from_schema().items():
            shortcuts.setdefault(path.replace("_", "-"), []).extend(
                flag for cli_flags in all_cli_flags for flag in cli_flags.flags
            )
        # A flag can only belong to one field, wherever it was declared
        claimed_by: dict[str, str] = {}
        for path, flags in shortcuts.items():
            for flag in flags:
                if flag in claimed_by:
                    raise ValueError(
                        f"Flag {flag!r} is claimed by both "
                        f"{claimed_by[flag]!r} and {path!r}"
                    )
                claimed_by[flag] = path

        # Precedence high->low: init kwargs, CLI, env, then config files.
        return (
            init_settings,
            CliSettingsSource(
                settings_cls,
                cli_parse_args=argv,
                cli_shortcuts=shortcuts,
            ),
            env_settings,
            ConfigFileSource(settings_cls),
        )
