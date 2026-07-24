from __future__ import annotations

import os
import sys
import warnings
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from anyio import Path
from pydantic import (
    BaseModel,
    ByteSize,
    Field,
    PrivateAttr,
    create_model,
    field_validator,
    model_validator,
)
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
    _MUTABLE,
    _MUTABLE_ALLOW,
    DEFAULT_SYSTEM_PROMPT,
    ApiConfig,
    CoreToolsConfig,
    InterfaceConfig,
    MCPServerConfig,
    PluginsConfig,
    SessionConfig,
    SystemPromptConfig,
)
from solveig.utils.file import Filesystem  # path normalization only (not config I/O)

if TYPE_CHECKING:
    from solveig.tools.base import BaseTool

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


def _compose_section(
    target: type[BaseModel],
    field_name: str,
    pairs: list[tuple[str, type]],
    model_name: str,
    config_dict: Any = _MUTABLE,
) -> None:
    """Build `target.<field_name>`'s real schema at runtime — one field per
    `(name, config_model)` pair — and swap it in (annotation + default_factory +
    `model_rebuild`). The single machinery both core (`config.tools`) and plugin
    (`config.plugins.tools`) tool config go through, so they get the same treatment.
    `config_dict` is `_MUTABLE_ALLOW` for the plugin section (PRESERVE unknown blocks)."""
    fields: dict[str, Any] = {
        name: (config_model, Field(default_factory=config_model))
        for name, config_model in pairs
    }
    with warnings.catch_warnings():
        # `copy` (CopyTool) deliberately shadows the deprecated BaseModel.copy.
        warnings.filterwarnings(
            "ignore", message=r'Field name "copy".*shadows', category=UserWarning
        )
        composed = create_model(model_name, __config__=config_dict, **fields)
    target.model_fields[field_name].annotation = composed
    target.model_fields[field_name].default_factory = composed
    target.model_rebuild(force=True)


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
    mcp: dict[str, MCPServerConfig] = Field(default_factory=dict)
    tools: CoreToolsConfig = Field(default_factory=CoreToolsConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    interface: InterfaceConfig = Field(default_factory=InterfaceConfig)
    system_prompt: SystemPromptConfig = Field(default_factory=SystemPromptConfig)
    briefing: list[str] = Field(
        default_factory=lambda: ["AGENTS.md"],
        description="Markdown files appended to the system prompt in order",
    )
    # ByteSize parses human strings ("1GiB") natively and gives .human_readable()
    # for display — no bespoke parse validator or display special-case needed.
    min_disk_space_left: ByteSize = Field(
        default=ByteSize(1024**3),  # 1 GiB
        description="Minimum free disk space before blocking writes",
    )
    auto_allowed_paths: list[Path] = Field(
        default_factory=list,
        description="Glob patterns for auto-approved file paths",
    )
    ignore_paths: list[Path] = Field(
        default_factory=list,
        description="Glob patterns for paths that are fully blocked from all tool access",
    )
    disable_autonomy: bool = Field(
        default=False, description="Require user approval between agentic steps"
    )

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

    @field_validator("auto_allowed_paths", "ignore_paths", mode="before")
    @classmethod
    def _abs_paths(cls, v: Any) -> Any:
        return [Filesystem.get_absolute_path(p) for p in v] if v else []

    @field_validator("mcp", mode="before")
    @classmethod
    def _normalize_mcp(cls, v: Any) -> Any:
        # Config files write a server block keyed by URL without repeating the
        # URL inside it (`mcp."http://x" = {name=…}`); inject the key as the
        # entry's `url` so every MCPServerConfig is complete.
        if not isinstance(v, dict):
            return v
        out: dict[str, Any] = {}
        for url, cfg in v.items():
            if isinstance(cfg, MCPServerConfig):
                out[url] = cfg
            else:
                rest = {k: val for k, val in dict(cfg).items() if k != "url"}
                out[url] = MCPServerConfig(url=url, **rest)
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

    def is_tool_enabled(self, tool_name: str) -> bool:
        """The single enable/disable rule for a tool, by name — the one home that
        spans every namespace a tool's `enabled` flag can live in: a core tool
        (`tools.<name>`) or a plugin tool (`plugins.tools.<name>`) is on iff its
        `.enabled` flag is set; an unknown name → True (on by default). Both the
        LLM-path filter (`is_tool_active`) and the `run_tool_and_hooks` guard use
        this one rule."""
        tools = self.tools
        if tool_name in type(tools).model_fields:
            return bool(getattr(tools, tool_name).enabled)
        plugin_tools = self.plugins.tools
        if tool_name in type(plugin_tools).model_fields:
            return bool(getattr(plugin_tools, tool_name).enabled)
        return True

    def is_hook_enabled(self, hook_name: str) -> bool:
        """The enable/disable rule for a hook, by name — the parallel of
        `is_tool_enabled` for the `plugins.hooks.<name>` namespace. A hook is on iff
        its `.enabled` flag is set; an unknown name → True (on by default). The gate
        `run_tool_and_hooks` consults before firing each registered hook."""
        hooks = self.plugins.hooks
        if hook_name in type(hooks).model_fields:
            return bool(getattr(hooks, hook_name).enabled)
        return True

    @classmethod
    def compose_core_tools(cls, tools: list[type[BaseTool]]) -> None:
        """Build the `config.tools` section from the core tool list — one field per
        tool (`tool_name()` → its `config_model`) — so `config` never hand-enumerates
        core tools; adding a core tool needs no change here.

        Called once from `config/__init__.py` *after* the `SolveigConfig` re-export
        (the load order that lets each tool module resolve its top-level `from
        solveig.config import SolveigConfig`), and re-run only on a genuine
        tool-membership change — never per tool call."""
        pairs = [(tool.tool_name(), tool.config_model) for tool in tools]
        _compose_section(cls, "tools", pairs, "CoreToolsConfig")

    @classmethod
    def compose_plugin_tools(cls, plugin_tools: list[Any]) -> None:
        """Build the `config.plugins.tools` section from the discovered plugin tools
        — the plugin parallel of `compose_core_tools`, and phase 2 of the two-phase
        bootstrap (parse → discover → compose → reparse). Reads each entry's config
        type via `config_model_of` (a `BaseTool` ClassVar or a callable's
        `@tool(config_model=…)` stash), so plugin config validates like core config.
        Rebuilds `SolveigConfig` too, since it embeds `PluginsConfig`."""
        from solveig.plugins.tools import config_model_of, plugin_tool_name

        pairs = [(plugin_tool_name(e), config_model_of(e)) for e in plugin_tools]
        _compose_section(
            PluginsConfig, "tools", pairs, "PluginToolsConfig", _MUTABLE_ALLOW
        )
        cls.model_rebuild(force=True)

    @classmethod
    def compose_plugin_hooks(cls, hooks: list[tuple[str, type]]) -> None:
        """Build the `config.plugins.hooks` section from the discovered hooks — the
        hook parallel of `compose_plugin_tools`, also part of phase 2 of the two-phase
        bootstrap. Takes the `(hook_name, config_model)` pairs `all_hooks()` already
        deduped (a hook is a function, so there's no generic to auto-derive from — its
        config type is a `@before/@after(config_model=…)` stash or bare `ToolConfig`).
        Rebuilds `SolveigConfig` too, since it embeds `PluginsConfig`."""
        _compose_section(
            PluginsConfig, "hooks", hooks, "PluginHooksConfig", _MUTABLE_ALLOW
        )
        cls.model_rebuild(force=True)

    def declared_config(self) -> dict[str, Any]:
        """The nested dict of only the explicitly-declared fields (file / CLI /
        `/config set`, tracked in `_declared`) — what `/config save` persists.

        `_declared` is the single source of truth for "was this set?"; each of its
        dotted paths is by construction a real leaf of the serialized config, so we
        just copy those leaves out of `model_dump(mode="json")` (which applies the
        field serializers: key un-masked, enums → names, byte sizes → ints, command
        patterns → source strings), walking source and destination in lockstep.
        """
        full = self.model_dump(mode="json")
        out: dict[str, Any] = {}
        for path in sorted(self._declared):
            *parents, leaf = path.split(".")
            src: Any = full
            dest = out
            for part in parents:
                src = src[part]
                dest = dest.setdefault(part, {})
            dest[leaf] = src[leaf]
        return out

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

        def _parse() -> SolveigConfig:
            token = _PENDING_ARGV.set(argv)
            try:
                return cls()  # pydantic parses CLI + env + files, then validates
            finally:
                _PENDING_ARGV.reset(token)

        # Two-phase bootstrap: parse once to learn plugins.paths, discover plugin
        # tools, and compose the plugins.tools schema — so the second parse validates
        # plugin config against the real per-plugin models, the same pipeline core
        # config goes through. Discovery is idempotent (setup_loop re-runs it for
        # interface-side reporting). It currently scans the built-in plugins package;
        # external plugins.paths scanning is what makes phase 1's config load-bearing.
        phase1 = _parse()
        from solveig.plugins import discover_plugins
        from solveig.plugins.hooks import all_hooks
        from solveig.plugins.tools import PLUGIN_TOOLS

        discover_plugins(phase1)
        cls.compose_plugin_tools(PLUGIN_TOOLS)
        cls.compose_plugin_hooks(all_hooks())

        cfg = _parse()
        cfg._loaded_paths = sources.resolve_config_files(cfg.config)
        cfg._record_declared(argv)
        for url in cfg.add_mcp:
            cfg.mcp.setdefault(url, MCPServerConfig(url=url))
        return cfg, cfg.prompt.strip(), cfg.resume
