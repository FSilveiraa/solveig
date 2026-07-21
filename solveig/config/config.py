from __future__ import annotations

import os
import sys
from contextvars import ContextVar
from typing import Any

from anyio import Path
from pydantic import Field, PrivateAttr, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    CliPositionalArg,
    CliSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from solveig.api import ModelInfo
from solveig.config import sources
from solveig.config.models import (
    DEFAULT_SYSTEM_PROMPT,
    ApiConfig,
    InterfaceConfig,
    McpConfig,
    MCPServerConfig,
    PluginsConfig,
    SessionConfig,
    SystemPromptConfig,
    ToolsConfig,
)
from solveig.utils.file import Filesystem  # path normalization only (not config I/O)
from solveig.utils.misc import parse_human_readable_size

# DEFAULT_SYSTEM_PROMPT lives in models.py (imported above) and is re-exported here
# for stable `solveig.config.config.DEFAULT_SYSTEM_PROMPT` / `solveig.config` imports.
__all__ = ["DEFAULT_CONFIG_PATH", "DEFAULT_SYSTEM_PROMPT", "SolveigConfig"]

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.solveig/config.json")

DEFAULT_PLUGIN_PATHS = [
    "./.solveig/plugins",
    "~/.solveig/plugins",
]  # built-in dir prepended by loader (Task 8)

# CliSettingsSource options — mirrors tools/base.py CLI_PARSE_OPTS.
# cli_avoid_json=True => nested fields become dotted flags (--api.url) not JSON blobs.
_CLI_OPTS: dict[str, Any] = {
    "cli_avoid_json": True,
    "cli_exit_on_error": False,
    "cli_kebab_case": False,
    "cli_implicit_flags": True,
    "cli_enforce_required": False,
}
# Friendly namespace-dropping LONG aliases (bare names -> --url etc). NOT -x short flags.
# Maps the CLI-only `add_mcp` append field to --mcp-server. NOTE: this cannot be
# the historical bare --mcp — under nested pydantic-settings the `mcp` submodel
# field itself owns the bare `--mcp` flag (a whole-model JSON fallback that a
# cli_shortcut can't override), so the repeatable startup flag is spelled
# --mcp-server <url> instead.
_CLI_SHORTCUTS: dict[str, str] = {
    "api.url": "url",
    "api.model": "model",
    "api.key": "key",
    "api.type": "api-type",
    "api.temperature": "temperature",
    "api.max_context": "max-context",
    "system_prompt.add_examples": "add-examples",
    "system_prompt.add_os_info": "add-os-info",
    "add_mcp": "mcp-server",
}

# Top-level CLI-only / runtime field names — parsed from argv or set at runtime but
# never persisted, so they must not leak into `_declared` (the /config save set).
_CLI_ONLY_FIELDS: frozenset[str] = frozenset({"prompt", "config", "resume", "add_mcp"})

# The argv to parse during a parse_config_and_prompt() call. When None (default),
# SolveigConfig(...) is a plain HERMETIC construction from explicit kwargs only —
# no ambient CLI or config-file reads (important for tests + the ripple's direct
# constructions). Set only for the duration of one parse.
_PENDING_ARGV: ContextVar[list[str] | None] = ContextVar("_pending_argv", default=None)


def _dotted_leaves(data: dict[str, Any], prefix: str = "") -> set[str]:
    """Flatten a nested provided-config dict into dotted leaf paths (`api.url`,
    `tools.http.timeout`). Powers `_declared` — the set of explicitly-set fields
    `/config save` persists."""
    out: set[str] = set()
    for key, value in (data or {}).items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            out |= _dotted_leaves(value, f"{path}.")
        else:
            out.add(path)
    return out


class AnyconfigSource(PydanticBaseSettingsSource):
    """Config-file layer. Reads the `--config` value the CLI source already
    parsed (via `current_state`) plus the default search paths, and loads+merges
    them with anyconfig. Config I/O is deliberately delegated here (bypasses
    Filesystem)."""

    def get_field_value(self, field, field_name):  # whole-dict source
        return None, "", False

    def __call__(self) -> dict[str, Any]:
        explicit = self.current_state.get("config")
        return sources.load_paths(sources.resolve_config_files(explicit))


class SolveigConfig(BaseSettings):
    # NOTE: the _CLI_OPTS keys are inlined here (rather than **-expanded) so mypy
    # can check them against the SettingsConfigDict TypedDict; the same dict is
    # **-expanded into CliSettingsSource(...) below, where a plain dict is fine.
    model_config = SettingsConfigDict(
        validate_assignment=True,
        arbitrary_types_allowed=True,
        env_prefix="SOLVEIG_",
        env_nested_delimiter="__",
        cli_avoid_json=True,
        cli_exit_on_error=False,
        cli_kebab_case=False,
        cli_implicit_flags=True,
        cli_enforce_required=False,
    )

    # --- persistent config ---
    api: ApiConfig = Field(default_factory=ApiConfig)
    plugins: PluginsConfig = Field(
        default_factory=lambda: PluginsConfig(paths=list(DEFAULT_PLUGIN_PATHS))
    )
    mcp: McpConfig = Field(default_factory=McpConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    interface: InterfaceConfig = Field(default_factory=InterfaceConfig)
    system_prompt: SystemPromptConfig = Field(default_factory=SystemPromptConfig)
    briefing: list[str] = Field(default_factory=lambda: ["AGENTS.md"])
    min_disk_space_left: int = parse_human_readable_size("1GiB")
    auto_allowed_paths: list[Path] = Field(default_factory=list)
    ignore_paths: list[Path] = Field(default_factory=list)
    disable_autonomy: bool = False

    # --- CLI-only inputs (parsed from the command line, never persisted) ---
    prompt: CliPositionalArg[str] = Field(default="", exclude=True)
    config: str | None = Field(
        default=None, exclude=True
    )  # --config: which file to read
    resume: str | None = Field(default=None, exclude=True)  # --resume [name]
    add_mcp: list[str] = Field(
        default_factory=list, exclude=True
    )  # --mcp-server URL (repeatable)
    # NOTE: command is not special — it's disabled the same uniform way as any core
    # tool (`--tools.command.enabled false`), so there is no `--no-commands` sugar.

    # --- runtime (not persisted; NOT a config field) ---
    # model_info is API-reported model facts (context length, pricing) fetched at
    # startup and cached for the stats bar — never user-set, so it's a PrivateAttr
    # (kept off the CLI + out of model_dump) exposed via the model_info property.
    _model_info: ModelInfo | None = PrivateAttr(default=None)
    # provenance for /config save (highest-precedence loaded file = [0])
    _loaded_paths: list[str] = PrivateAttr(default_factory=list)
    # dotted paths explicitly set via file/CLI/`/config set` — what /config save persists
    _declared: set[str] = PrivateAttr(default_factory=set)

    @property
    def model_info(self) -> ModelInfo | None:
        return self._model_info

    @model_info.setter
    def model_info(self, value: ModelInfo | None) -> None:
        self._model_info = value

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        argv = _PENDING_ARGV.get()
        if argv is None:
            # Direct construction from explicit kwargs — hermetic, no CLI/file/env reads.
            return (init_settings,)
        # Precedence high->low: CLI, env (SOLVEIG_*), then config files. pydantic
        # deep-merges nested models across sources and validates.
        cli = CliSettingsSource(
            settings_cls,
            cli_parse_args=argv,
            cli_shortcuts=_CLI_SHORTCUTS,
            **_CLI_OPTS,
        )
        return (init_settings, cli, env_settings, AnyconfigSource(settings_cls))

    @field_validator("min_disk_space_left", mode="before")
    @classmethod
    def _parse_size(cls, v: Any) -> Any:
        return parse_human_readable_size(v)

    @field_validator("auto_allowed_paths", "ignore_paths", mode="before")
    @classmethod
    def _abs_paths(cls, v: Any) -> Any:
        return [Filesystem.get_absolute_path(p) for p in v] if v else []

    @model_validator(mode="after")
    def _default_api_url(self):
        # api.type always has a default (OPENAI); when no url is given, derive it
        # from the type's default endpoint. (This replaces the old "must specify
        # --url or --api-type" gate: giving nothing now resolves to the OpenAI
        # default endpoint rather than erroring — a deliberate simplification.)
        if not self.api.url:
            default = self.api.type.default_url
            if not default:
                raise ValueError(
                    f"API type {self.api.type.name} has no default URL; pass --url."
                )
            self.api.url = default
        return self

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_json(self, indent: int | None = 2, **kw) -> str:
        return self.model_dump_json(indent=indent, **kw)

    def _record_declared(self, argv: list[str]) -> None:
        """Populate `_declared` with the dotted paths explicitly provided by the
        config file(s) and the command line — the fields `/config save` persists.
        Env-provided values are transient and intentionally excluded."""
        cli: CliSettingsSource = CliSettingsSource(
            type(self), cli_parse_args=argv, cli_shortcuts=_CLI_SHORTCUTS, **_CLI_OPTS
        )
        # Flatten each source to dotted leaves and union the sets — a shallow dict
        # merge would let one source's `api` sub-dict clobber the other's.
        declared = _dotted_leaves(sources.load_paths(self._loaded_paths))
        declared |= _dotted_leaves(cli() or {})
        self._declared = {
            path for path in declared if path.split(".", 1)[0] not in _CLI_ONLY_FIELDS
        }

    @classmethod
    async def parse_config_and_prompt(cls, cli_args=None):
        argv = list(sys.argv[1:] if cli_args is None else cli_args)
        token = _PENDING_ARGV.set(argv)
        try:
            cfg = cls()  # pydantic parses the whole CLI + env + files, then validates
        finally:
            _PENDING_ARGV.reset(token)
        cfg._loaded_paths = sources.resolve_config_files(cfg.config)
        cfg._record_declared(argv)
        for url in cfg.add_mcp:
            cfg.mcp.servers.setdefault(url, MCPServerConfig(url=url))
        return cfg, cfg.prompt.strip(), cfg.resume
