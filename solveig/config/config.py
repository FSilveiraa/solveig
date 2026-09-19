from __future__ import annotations

import argparse
import re
import sys
import warnings
from typing import Any, Annotated

from pydantic import (
    BaseModel,
    ByteSize,
    Field,
    SecretStr,
    create_model,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    CliPositionalArg,
    CliSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from solveig.api.types import ApiConfig
from solveig.config import sources
from solveig.config.models import (
    DynamicSection,
    Choice,
    ConfigPath,
    ConfigSection,
    PreservingSection, CliFlags,
)
from solveig.interface.config import InterfaceConfig
from solveig.mcp_servers.config import MCPServerConfig
from solveig.plugins.config import PluginsConfig
from solveig.session.config import SessionConfig
from solveig.system_prompt.config import SystemPromptConfig
from solveig.tools.config import CoreToolsConfig
from solveig.utils.file import Filesystem  # path normalization, not config I/O
from solveig.utils.misc import CLI_SETTINGS_OPTS

__all__ = [
    "SolveigConfig",
    "ConfigSection",
    "DynamicSection",
    "PreservingSection",
]


def _split_config_path_from_cli_args(
    argv: list[str],
) -> tuple[list[str], list[str]]:
    """Pull every `--config FILE` out of argv, returning (config_paths,
    remaining_argv). `--config` is consumed by the config-file source."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", action="append", dest="config", default=[])
    ns, rest = parser.parse_known_args(argv)
    return ns.config, rest


def _cli_flags_from_schema(model: type[ConfigSection]) -> dict[str, list[str]]:
    """
    Finds all CLI shortcut flags for a config root, returns a mapping of  maps their paths to their CLI flags.
    :return Mapping of each field's path to their CLI shortcut flags.
    :raises ValueError if 2 fields declare the same shortcut.
    """
    path_to_flags: dict[str, list[str]] = {}
    claimed_by: dict[str, str] = {}
    # `skip_excluded_fields=False`, un-exported fields can still declare CLI shortcuts
    for path, field_info in model.walk_schema(skip_excluded=False):
        cli_flags = [
            flag
            for metadata in field_info.metadata
            if isinstance(metadata, CliFlags)
            for flag in metadata.flags
        ]
        if not cli_flags:
            continue

        # Check whether this flag was previously used, raise on conflicts
        # NOTE: this design allows defining multiple groups of flags, but nothing
        #  prevents them from defining the same flag 5 times, and then the error
        #  message will say "Flag 'x' is claimed by both MyClass and MyClass".
        for flag in cli_flags:
            if flag in claimed_by:
                raise ValueError(
                    f"Flag {flag!r} is claimed by both "
                    f"{claimed_by[flag]} and {path!r}"
                )
            claimed_by[flag] = path
        # Add all the found flags to the result map
        path_to_flags.setdefault(path, []).extend(cli_flags)

    return path_to_flags


class ConfigFileSource(PydanticBaseSettingsSource):
    """A pydantic-settings class modeling one config file passed through `--config FILE`.
    Resolved paths get loaded by pydantic-settings and stored in `config.config_files`."""

    def __init__(self, settings_cls, requested: list[str] | None = None):
        super().__init__(settings_cls)
        self._requested = requested or []

    # pydantic base-class override
    def get_field_value(self, field, field_name):
        return None, "", False

    def __call__(self) -> dict[str, Any]:
        resolved = sources.resolve_config_files(self._requested)
        data = sources.load_paths(resolved)
        data["config_files"] = resolved  # stamp so the field is the one home
        return data


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------


def display_config_value(value: object, field_info: FieldInfo | None = None) -> str:
    """Format a config value for display, driven by type and field name."""
    choice = next(
        (m for m in field_info.metadata if isinstance(m, Choice)),
        None,
    ) if field_info else None
    if choice:
        return choice.key(value)
    if isinstance(value, SecretStr):
        return "***" if value.get_secret_value() else "(not set)"
    if isinstance(value, ByteSize):
        return value.human_readable()
    if isinstance(value, re.Pattern):
        return value.pattern
    if isinstance(value, list):
        return ", ".join(display_config_value(v) for v in value) if value else "(empty)"
    return repr(value)


def _compose_section(
    target: type[BaseModel],
    field_name: str,
    pairs: list[tuple[str, type]],
    model_name: str,
    base: type[BaseModel] = DynamicSection,
) -> None:
    """Build a composed model from (name, config_model) pairs and swap it into
    `target.<field_name>` — one field per entry, so adding a tool/hook needs
    no change here.

    NOTE: the composed model SUBCLASSES the placeholder rather than copying its
    `model_config`, so the section's semantics travel with it — plugin sections
    inherit `PreservingSection` and keep both `extra="allow"` and the
    `undiscovered` accessor. (pydantic forbids `__base__` and `__config__`
    together, which is why the base carries the config.)
    """
    fields: dict[str, Any] = {
        name: (config_model, Field(default_factory=config_model))
        for name, config_model in pairs
    }
    with warnings.catch_warnings():
        # HACK: `copy` (CopyTool) deliberately shadows the deprecated BaseModel.copy.
        warnings.filterwarnings(
            "ignore", message=r'Field name "copy".*shadows', category=UserWarning
        )
        composed = create_model(model_name, __base__=base, **fields)
    target.model_fields[field_name].annotation = composed
    target.model_fields[field_name].default_factory = composed
    target.model_rebuild(force=True)


class SolveigConfig(BaseSettings, ConfigSection):
    # NOTE: SolveigConfig inherits ConfigSection to get the validation and
    # `extra="forbid"` behavior from its model_config
    # ------------------------------------------------------------
    # Pydantic model config
    # ------------------------------------------------------------
    # NOTE: the cli_* keys from CLI_OPTS are inlined here (rather than
    # **-expanded) so mypy can check them against the SettingsConfigDict
    # TypedDict. The actual CLI parsing goes through the hand-built
    # CliSettingsSource in settings_customise_sources, which reads
    # CLI_SETTINGS_OPTS — these model_config copies are a mypy formality,
    # not the runtime config.
    model_config = SettingsConfigDict(
        env_prefix="SOLVEIG_",
        env_nested_delimiter="__",
        cli_avoid_json=True,
        cli_exit_on_error=CLI_SETTINGS_OPTS.get("cli_exit_on_error", False),
        cli_kebab_case=CLI_SETTINGS_OPTS.get("cli_kebab_case", False),
        cli_implicit_flags=CLI_SETTINGS_OPTS.get("cli_implicit_flags", True),
        cli_enforce_required=CLI_SETTINGS_OPTS.get("cli_enforce_required", False),
    )

    # ------------------------------------------------------------
    # Persisted config fields
    # ------------------------------------------------------------
    api: ApiConfig = Field(default_factory=ApiConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    mcp: dict[str, MCPServerConfig] = Field(default_factory=dict)
    tools: CoreToolsConfig = Field(default_factory=CoreToolsConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    interface: InterfaceConfig = Field(default_factory=InterfaceConfig)
    system_prompt: SystemPromptConfig = Field(default_factory=SystemPromptConfig)
    briefing: list[str] = Field(
        default_factory=lambda: ["AGENTS.md"],
        description="Markdown files appended to the system prompt in order",
    )
    minimum_disk_space_left: ByteSize = Field(
        default=ByteSize(1024**3),  # 1 GiB
        description="Minimum free disk space before blocking writes",
    )
    auto_allowed_paths: list[ConfigPath] = Field(
        default_factory=list,
        description="Glob patterns for auto-approved file paths",
    )
    ignored_paths: list[ConfigPath] = Field(
        default_factory=list,
        description="Glob patterns for paths that are fully blocked from all tool access",
    )
    disable_autonomy: bool = Field(
        default=False, description="Require user approval between agentic steps"
    )
    stream: bool = Field(
        default=True,
        description="Stream assistant output token-by-token as it's generated",
    )

    # ------------------------------------------------------------
    # CLI-only fields
    # ------------------------------------------------------------
    prompt: CliPositionalArg[str] = Field(default="", exclude=True)
    # The config files actually loaded — resolved (existence-checked) `--config`
    # paths, or the default search results when no --config was passed. Stamped
    # by ConfigFileSource at parse; [0] is the /config save target. The one home
    # for "which config files were loaded", so "nothing loaded" is []. NOT
    # `DEFAULT_CONFIG_PATHS`: that is the SEARCH list, and it holds an
    # unexpanded `~` that no reader here would resolve.
    config_files: list[ConfigPath] = Field(default_factory=list, exclude=True)
    resume: str | None = Field(default=None, exclude=True)  # --resume [name]
    startup_mcp_servers: Annotated[list[str], CliFlags("mcp-url")] = Field(
        default_factory=list, exclude=True
    )  # use `--mcp-url URL`
    # The CLI args this instance was booted from — always a list after
    # construction (never None). The source hook reads this as a constructor
    # kwarg: None → use sys.argv[1:], a list → use that, [] → hermetic.
    # parse_config_and_prompt stamps sys.argv[1:] when the kwarg was None,
    # so the field is a truthful durable record at every read site.
    cli_args: list[str] | None = Field(default=None, exclude=True)

    # ------------------------------------------------------------
    # Pydantic overrides/validators
    # ------------------------------------------------------------

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
        argv = init_settings.init_kwargs.get("cli_args")
        # `if not argv` accepts `argv==None`,which we want to pass
        # to pydantic-settings' parsing
        if argv == []:
            return (init_settings,)
        if argv is None:
            argv = sys.argv[1:]
        # `--config` belongs to the file source, not pydantic's CLI parser —
        # split it out so CliSettingsSource never sees a flag it would reject.
        config_paths, argv = _split_config_path_from_cli_args(argv)
        # Precedence high->low: CLI, env (SOLVEIG_*), then config files. pydantic
        # deep-merges nested models across sources and validates.
        cli = CliSettingsSource(
            settings_cls,
            cli_parse_args=argv,
            cli_shortcuts=_cli_flags_from_schema(settings_cls),
            **CLI_SETTINGS_OPTS,
            cli_avoid_json=True,
        )
        return (
            init_settings,
            cli,
            env_settings,
            ConfigFileSource(settings_cls, requested=config_paths),
        )

    @field_validator("auto_allowed_paths", "ignored_paths", mode="before")
    @classmethod
    def _abs_paths(cls, v: Any) -> Any:
        """Anchor the safety patterns the moment they are set.

        NOTE: load-bearing, not tidiness. Solveig's working directory MOVES - a
        `cd` inside a command takes the file tools with it - so a pattern that
        resolved lazily would mean something different after every `cd`, and
        `cd ..` would be an escape from an ignored subtree. A rule the subject
        can move by walking is not a rule. `resolve()` keeps glob metacharacters
        intact, so `*.log` anchors without being expanded.

        `resolve_pattern` owns the one exception (a bare name like `node_modules`
        is stored as written, so it keeps meaning "wherever this appears"); config
        states WHEN patterns are settled, not what a pattern means.
        """
        return [Filesystem.resolve_pattern(p) for p in v] if v else []

    @field_validator("briefing", mode="before")
    @classmethod
    def _abs_briefing(cls, v: Any) -> Any:
        """Anchored for the same reason, plus one of its own: the briefing is
        re-read every turn, so a relative `AGENTS.md` would silently become
        `docs/AGENTS.md` once the assistant moved, changing its own instructions
        mid-session."""
        return [str(Filesystem.get_absolute_path(p)) for p in v] if v else []

    @field_validator("mcp", mode="before")
    @classmethod
    def _normalize_mcp(cls, v: Any) -> Any:
        # A server block is keyed by NAME and does not repeat it inside
        # (`[mcp.parallel]` / `url = "…"`); inject the key so every
        # MCPServerConfig is complete and can be handed around on its own. The
        # mirror of this is `name`'s `exclude=True` — the key is where the name
        # lives on disk, so dumping it back into the block would create a second
        # home for it.
        if not isinstance(v, dict):
            return v
        out: dict[str, Any] = {}
        for name, cfg in v.items():
            if isinstance(cfg, MCPServerConfig):
                out[name] = cfg
            else:
                # Re-create the MCP server config from a dict to a config model instance
                mcp_config_nameless = dict(cfg)
                mcp_config_nameless.pop("name", None)
                out[name] = MCPServerConfig(name=name, **mcp_config_nameless)
        return out

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

    @field_serializer("minimum_disk_space_left")
    def _ser_min_disk(self, v: ByteSize) -> str:
        # Human-readable so a --full/--all config dump exports the default as
        # "1.0GiB" rather than 1073741824 (round-trips to the same value). The
        # /config save path grafts the exact original from _declared_fields, so
        # a user's "1GiB" is preserved verbatim there, not re-normalized here.
        return v.human_readable()





    # ------------------------------------------------------------
    # Tool/Hook section schema
    # ------------------------------------------------------------

    def is_tool_enabled(self, tool_name: str) -> bool:
        # The one home for "is this tool on?" — checks core tools, then
        # plugin tools, defaults to True for an unknown name.
        tools = self.tools
        if tool_name in type(tools).model_fields:
            return bool(getattr(tools, tool_name).enabled)
        plugin_tools = self.plugins.tools
        if tool_name in type(plugin_tools).model_fields:
            return bool(getattr(plugin_tools, tool_name).enabled)
        return True

    def is_hook_enabled(self, hook_name: str) -> bool:
        # The one home for "is this hook on?" — checks plugins.hooks.<name>,
        # defaults to True for an unknown name. run_tool_and_hooks consults
        # this before firing each registered hook.
        hooks = self.plugins.hooks
        if hook_name in type(hooks).model_fields:
            return bool(getattr(hooks, hook_name).enabled)
        return True

    # ------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------

    @classmethod
    def parse(cls, cli_args: list[str] | None = None) -> SolveigConfig:
        """One pass over the layered sources (CLI > env > files), nothing more.

        NOTE: the result is TRANSIENT. Startup uses it to read `plugins.paths`
        before the plugin schema exists, and drops it on the same line — the
        config that survives is the one `build()` returns, after composition.
        Anything that keeps a `parse()` result is holding an object whose plugin
        sections may no longer match the class, and whose observers nothing will
        ever notify. Use `build()`.
        """
        cfg = cls(cli_args=cli_args)
        if cfg.cli_args is None:
            cfg.cli_args = list(sys.argv[1:])
        return cfg

    @classmethod
    def build(cls, cli_args: list[str] | None = None) -> SolveigConfig:
        """`parse()` plus the finishing touches for the config that is kept:
        declared-field tracking (what `/config save` persists) and startup MCP
        servers.

        The two-phase dance around this (compose core tools → discover plugins
        → compose plugin sections → parse again) is startup sequencing and
        lives in `solveig.bootstrap`, above tools and plugins.
        """
        cfg = cls.parse(cli_args)
        # `--mcp-url` names a server only by address, so it gets the same derived
        # identifier an ad-hoc `/mcp connect <url>` would give it — and setdefault
        # means a config block already using that name wins, rather than the flag
        # silently replacing a configured server's allow/block lists.
        for url in cfg.startup_mcp_servers:
            # TODO: this should be absorbed some other way
            #  The fact that an MCP config is built from a URL is a fact
            #  that the MCP config class itself needs to express, not root.
            server = MCPServerConfig.from_url(url)
            cfg.mcp.setdefault(server.name, server)
        return cfg
