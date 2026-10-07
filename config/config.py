import argparse
import pathlib
import sys
from typing import Annotated, override

from pydantic import Field
from pydantic_settings import BaseSettings, CliSettingsSource, SettingsConfigDict

from config.models import ConfigSection, Path, CliFlags
from config.sources import ConfigFileSource


class Config(BaseSettings, ConfigSection):
    model_config = SettingsConfigDict(
        cli_avoid_json=True,
        cli_exit_on_error=False,
        cli_kebab_case=True,
        cli_implicit_flags=True,
        cli_enforce_required=False,
    )

    # Whether to read `sys.argv`. An internal switch, never saved or edited
    parse_cli: bool = Field(default=True, exclude=True)
    # Sorted lowest -> highest priority
    # `--config FILE`, repeatable. A subclass may add its own shortcuts
    #  (`CliFlags("c", "config")`) by redeclaring the field.
    config_files: Annotated[list[Path], CliFlags("config")] = Field(default_factory=list, exclude=True)
    # cli_args: list[str] = Field(default_factory=lambda: sys.argv[1:], exclude=True)

    @classmethod
    def _split_config_paths_from_cli_args(
            cls,
            argv: list[str],
    ) -> tuple[list[str], list[str]]:
        """
        Pull every `--config FILE` out of argv, returning (config_paths,
        remaining_argv). `--config` is consumed by the config-file source.
        """
        # Find the flags for `config_files`
        all_config_file_flags: list[CliFlags] = cls._cli_flags_from_schema("config_files")["config_files"]
        flat_config_file_flags = [
            flag
            for cli_flags in all_config_file_flags
            for flag in cli_flags.to_argparse()
        ]
        # Create an argparse parser to extract them from the CLI args
        config_file_path_parser = argparse.ArgumentParser(add_help=False)
        config_file_path_parser.add_argument(
            *flat_config_file_flags,
            action="append",
            dest="config", default=[]
        )
        namespace, rest = config_file_path_parser.parse_known_args(argv)
        return namespace.config, rest

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
        config_paths, argv = cls._split_config_paths_from_cli_args(argv)
        if not config_paths:
            config_paths = settings_cls.model_fields["config_files"].get_default(call_default_factory=True)
        config_paths = [ pathlib.Path(p).expanduser().resolve() for p in config_paths ]

        # For some reason pydantic-settings expect the keys (paths) to use kebab-case,
        #  and the values (cli flags) to use underscores. Expected:
        #  {"path.to.my-section": ["my-section", "m"]}
        #  Creates: `--my-section` and `-m`
        cli_flags = {
            path.replace("_", "-"): [
                flag
                for cli_flags in flags
                for flag in cli_flags.flags
            ]
            for path, flags in cls._cli_flags_from_schema().items()
        }

        # Precedence high->low: CLI, env (SOLVEIG_*), then config files.
        cli_settings = CliSettingsSource(
            settings_cls,
            cli_parse_args=argv,
            cli_shortcuts=cli_flags,
        )
        # NOTE: `config_files` is the record of which files were read. Files are
        #  chosen with `--config` on the command line, or by the field's default
        #  otherwise. The record is still an ordinary field, so a value given in
        #  code or through the environment replaces it without changing what was
        #  read: `App(config_files=[])` reads the default files but records none.
        #  Kept settable on purpose (files may later chain other files).
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


