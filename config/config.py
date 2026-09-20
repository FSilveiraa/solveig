import argparse
import sys
from typing import override

from pydantic import Field
from pydantic_settings import BaseSettings, CliSettingsSource, SettingsConfigDict

from config.models import ConfigSection, ConfigPath
from config.sources import ConfigFileSource


def _split_config_paths_from_cli_args(
    argv: list[str],
) -> tuple[list[str], list[str]]:
    """
    Pull every `--config FILE` out of argv, returning (config_paths,
    remaining_argv). `--config` is consumed by the config-file source.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", action="append", dest="config", default=[])
    ns, rest = parser.parse_known_args(argv)
    return ns.config, rest


class Config(BaseSettings, ConfigSection):
    model_config = SettingsConfigDict(
        cli_avoid_json=True,
        cli_exit_on_error=False,
        cli_kebab_case=True,
        cli_implicit_flags=True,
        cli_enforce_required=False,
    )

    parse_cli: bool = True
    # Sorted lowest -> highest priority
    config_files: list[ConfigPath] = Field(default_factory=list, exclude=True)
    # cli_args: list[str] = Field(default_factory=lambda: sys.argv[1:], exclude=True)

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
        """Build the settings-source stack. CLI args flow through cli_args;
        --config flags are split out for ConfigFileSource."""
        # Parse CLI args list. If `cli_args` is absent from init_kwargs,
        # then it wasn't passed, use field default
        parse_cli: bool | None = init_settings.init_kwargs.get("parse_cli")
        if parse_cli is None:
            parse_cli = settings_cls.model_fields["parse_cli"].get_default()
        argv = sys.argv[1:] if parse_cli else []

        # Parse config file flags. Remove `--config` from CLI args so
        # it doesn't get parsed by pydantic, use it to parse file sources
        config_paths, argv = _split_config_paths_from_cli_args(argv)
        if not config_paths:
            config_paths = settings_cls.model_fields["config_files"].get_default(call_default_factory=True)

        # Precedence high->low: CLI, env (SOLVEIG_*), then config files.
        cli_settings = CliSettingsSource(
            settings_cls,
            cli_parse_args=argv,
            cli_shortcuts=cls._cli_flags_from_schema(),
        )
        # TODO: ConfigFileSource contains its own internal defaults,
        #  built from default name templates and known extensions. This
        #  is not reflected in the field's default at all, and there's
        #  no way to fully ignore the default configs anymore. Needs
        #  urgent fixing, most tests likely broken.
        file_settings = ConfigFileSource(
            settings_cls,
            requested=config_paths,
            field_name="config_files",
        )
        return (
            init_settings,
            cli_settings,
            env_settings,
            file_settings,
        )
