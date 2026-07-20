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
    ApiConfig,
    InterfaceConfig,
    McpConfig,
    MCPServerConfig,
    PluginsConfig,
    SessionConfig,
    ToolsConfig,
)
from solveig.utils.file import Filesystem  # path normalization only (not config I/O)
from solveig.utils.misc import parse_human_readable_size

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.solveig/config.json")

DEFAULT_SYSTEM_PROMPT = """
You are an AI assistant helping a user through a tool called Solveig that allows you to call tools.

Guidelines:
- The `comment` field is required for all communication with the user (supports Markdown formatting)
- For multi-step work, include a tasks list in your response showing your plan
- For simple requests, avoid plans and respond directly
- Update task status (pending → ongoing → completed/failed) as you progress
- Work autonomously - continue executing operations until the task is complete
- Prefer file operations over shell commands when possible
- Avoid unnecessary destructive actions (delete, overwrite)
- If an operation fails, adapt your approach and continue

Response format:
- comment: Required field for all communication and explanations (use Markdown formatting)
- tasks: Optional array of Task(description, status) objects
- tools: Optional list of tools to use
"""

DEFAULT_PLUGIN_PATHS = [
    "./plugins",
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
    "add_mcp": "mcp-server",
}

# The argv to parse during a parse_config_and_prompt() call. When None (default),
# SolveigConfig(...) is a plain HERMETIC construction from explicit kwargs only —
# no ambient CLI or config-file reads (important for tests + the ripple's direct
# constructions). Set only for the duration of one parse.
_PENDING_ARGV: ContextVar[list[str] | None] = ContextVar("_pending_argv", default=None)


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
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    briefing: list[str] = Field(default_factory=lambda: ["AGENTS.md"])
    add_examples: bool = False
    add_os_info: bool = False
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
    )  # --mcp URL (repeatable)

    # --- runtime (not persisted) ---
    model_info: ModelInfo | None = Field(default=None, exclude=True)
    # provenance for /config save (highest-precedence loaded file = [0])
    _loaded_paths: list[str] = PrivateAttr(default_factory=list)

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
            # Direct construction from explicit kwargs — hermetic, no CLI/file reads.
            return (init_settings,)
        # CLI (highest precedence) then config files; pydantic deep-merges + validates.
        cli = CliSettingsSource(
            settings_cls,
            cli_parse_args=argv,
            cli_shortcuts=_CLI_SHORTCUTS,
            **_CLI_OPTS,
        )
        return (init_settings, cli, AnyconfigSource(settings_cls))

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

    @classmethod
    async def parse_config_and_prompt(cls, cli_args=None):
        argv = list(sys.argv[1:] if cli_args is None else cli_args)
        token = _PENDING_ARGV.set(argv)
        try:
            cfg = cls()  # pydantic parses the whole CLI + files, then validates
        finally:
            _PENDING_ARGV.reset(token)
        cfg._loaded_paths = sources.resolve_config_files(cfg.config)
        for url in cfg.add_mcp:
            cfg.mcp.servers.setdefault(url, MCPServerConfig(url=url))
        return cfg, cfg.prompt.strip(), cfg.resume
