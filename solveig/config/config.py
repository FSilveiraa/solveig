from __future__ import annotations

import argparse
import os
import sys
import warnings
from typing import Any, Protocol

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

# DEFAULT_SYSTEM_PROMPT lives in models.py (imported above) and is re-exported here
# for stable `solveig.config.config.DEFAULT_SYSTEM_PROMPT` / `solveig.config` imports.
__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_SYSTEM_PROMPT",
    "ConfigObserver",
    "SolveigConfig",
    "get_config_value",
    "set_config_value",
]

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.solveig/config.json")

DEFAULT_PLUGIN_PATHS = [
    "./.solveig/plugins",
    "~/.solveig/plugins",
]  # built-in dir prepended by loader (Task 8)

# Options for CliSettingsSource to parse — mirrors tools/base.py CLI_PARSE_OPTS.
_CLI_OPTS: dict[str, Any] = {
    "cli_avoid_json": True,  # makes ested fields become dotted flags (--api.url) not JSON blobs.
    "cli_exit_on_error": False,
    "cli_kebab_case": False,
    "cli_implicit_flags": True,
    "cli_enforce_required": False,
}
# Friendly namespace-dropping LONG aliases (bare names -> --url etc). NOT -x short flags.
_CLI_SHORTCUTS: dict[str, str] = {
    "api.url": "url",
    "api.model": "model",
    "api.key": "key",
    "api.type": "api-type",
    "api.temperature": "temperature",
    "api.max_context": "max-context",
    "system_prompt.add_examples": "add-examples",
    "system_prompt.add_os_info": "add-os-info",
    # NOTE: `config_files` is NOT a CLI shortcut — the `--config` flag is split
    # out of argv and consumed by ConfigFileSource, which stamps the RESOLVED
    # paths onto the field. Exposing it as a CLI flag would collide with that.
    # `--mcp` can't be used since it's already config field, so `--mcp-url`
    # accumulates into `startup_mcp_servers` and later populates `.mcp`
    "startup_mcp_servers": "mcp-url",
}


def _split_config_flags(argv: list[str]) -> tuple[list[str], list[str]]:
    """Pull every `--config FILE` out of argv, returning (config_paths,
    remaining_argv). `--config` is consumed by the config-file source, NOT
    parsed as a pydantic CLI flag — removing it here lets CliSettingsSource
    parse the rest without erroring on an unknown flag."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", action="append", dest="config", default=[])
    ns, rest = parser.parse_known_args(argv)
    return ns.config, rest


class ConfigObserver(Protocol):
    """Subscriber for runtime config changes. Config is the source of truth and emits
    config + changed fields to observers who (stats update, provider model fetch, …)."""

    async def config_changed(
        self, config: SolveigConfig, paths: frozenset[str]
    ) -> None: ...


class ConfigFileSource(PydanticBaseSettingsSource):
    """Config-file layer. The `--config FILE` paths arrive already split out of
    argv by `settings_customise_sources` (`requested`). They are resolved
    (existence-checked) or replaced by the default search paths, loaded+merged
    with anyconfig, and the RESOLVED paths are stamped into the returned dict's
    `config_files` key — making that field the one home for "which config files
    were actually loaded". A non-existent user-passed path is dropped here (the
    historical record is `cli_args`).
    NOTE: this component does file I/O bypassing the Filesystem module"""

    def __init__(self, settings_cls, requested: list[str] | None = None):
        super().__init__(settings_cls)
        self._requested = requested or []

    def get_field_value(self, field, field_name):  # whole-dict source
        return None, "", False

    def __call__(self) -> dict[str, Any]:
        resolved = sources.resolve_config_files(self._requested)
        data = sources.load_paths(resolved)
        data["config_files"] = resolved
        return data


# ---------------------------------------------------------------------------
# Dotted paths — the one home for addressing a config leaf by dotted string
# (`api.url`, `tools.http.timeout`). Used by _declared tracking, /config set,
# notify fan-out. Editor (UI) imports get_config_value/set_config_value.
# ---------------------------------------------------------------------------


def _resolve(config: SolveigConfig, dotted: str) -> tuple[Any, str]:
    """Walk a dotted path to its leaf, returning (owning_model, leaf_name)."""
    obj: Any = config
    *parents, leaf = dotted.split(".")
    for part in parents:
        obj = getattr(obj, part)
    return obj, leaf


def get_config_value(config: SolveigConfig, dotted: str) -> Any:
    obj, leaf = _resolve(config, dotted)
    return getattr(obj, leaf)


def set_config_value(config: SolveigConfig, dotted: str, value: Any) -> Any:
    """Set a dotted leaf; returns the previous value. validate_assignment on
    the leaf's owning model re-validates (str → APIType/Palette/ByteSize, …)."""
    obj, leaf = _resolve(config, dotted)
    old = getattr(obj, leaf)
    setattr(obj, leaf, value)
    return old


def _dict_to_dotted_leaves(data: dict[str, Any], prefix: str = "") -> set[str]:
    """Flatten a nested config dict into dotted leaf paths (`api.url`,
    `tools.http.timeout`) — the same language /config set and notify speak."""
    out: set[str] = set()
    for key, value in (data or {}).items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            out |= _dict_to_dotted_leaves(value, f"{path}.")
        else:
            out.add(path)
    return out


def _compose_section(
    target: type[BaseModel],
    field_name: str,
    pairs: list[tuple[str, type]],
    model_name: str,
    config_dict: Any = _MUTABLE,
) -> None:
    """Attach one validated field per entry to a placeholder section by
    rebuilding the model class — `config.tools` and `config.plugins.*` get
    their real schema from the tool/hook list, so adding one touches nothing
    here. `config_dict` is `_MUTABLE_ALLOW` for plugin sections (an unknown
    plugin's config block PRESERVES through /config save as `model_extra`).

    Example:
        target=PluginsConfig, field_name="hooks",
        pairs=[("shellcheck", ShellcheckConfig), ("trafilatura", ToolConfig)]
        → PluginsConfig.hooks becomes a model with fields
          {shellcheck: ShellcheckConfig, trafilatura: ToolConfig}.
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
        composed = create_model(model_name, __config__=config_dict, **fields)
    target.model_fields[field_name].annotation = composed
    target.model_fields[field_name].default_factory = composed
    target.model_rebuild(force=True)


class SolveigConfig(BaseSettings):
    # ------------------------------------------------------------
    # Pydantic model config
    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # Persisted config fields
    # ------------------------------------------------------------
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
    min_disk_space_left: ByteSize = Field(
        default=ByteSize(1024**3),  # 1 GiB
        description="Minimum free disk space before blocking writes",
    )
    auto_allowed_paths: list[Path] = Field(
        default_factory=list,
        description="Glob patterns for auto-approved file paths",
    )
    ignored_paths: list[Path] = Field(
        default_factory=list,
        description="Glob patterns for paths that are fully blocked from all tool access",
    )
    disable_autonomy: bool = Field(
        default=False, description="Require user approval between agentic steps"
    )

    # ------------------------------------------------------------
    # CLI-only fields
    # ------------------------------------------------------------
    prompt: CliPositionalArg[str] = Field(default="", exclude=True)
    # The config files actually loaded — resolved (existence-checked) `--config`
    # paths, or the default search results when no --config was passed. Stamped
    # by ConfigFileSource at parse; [0] is the /config save target. The one home
    # for "which config files were loaded".
    config_files: list[str] = Field(default_factory=list, exclude=True)
    resume: str | None = Field(default=None, exclude=True)  # --resume [name]
    startup_mcp_servers: list[str] = Field(
        default_factory=list, exclude=True
    )  # use `--mcp-url URL`
    # The argv to parse, as a tri-state constructor kwarg read back by
    # settings_customise_sources (via init_settings) to build the CLI source:
    #   None (default) → parse the real process argv
    #   a list         → parse that argv instead (tests, embedded use)
    #   []             → hermetic — no CLI/env/file reads at all
    cli_args: list[str] | None = Field(default=None, exclude=True)

    # ------------------------------------------------------------
    # Runtime fields (unpersisted)
    # ------------------------------------------------------------
    # dotted paths explicitly set via file/CLI/`/config set` — what /config save persists
    _declared_fields: set[str] = PrivateAttr(default_factory=set)
    # observers for field changes
    _observers: list[ConfigObserver] = PrivateAttr(default_factory=list)

    # ------------------------------------------------------------
    # Config change observers
    # ------------------------------------------------------------
    def subscribe(self, observer: ConfigObserver) -> None:
        """Register a runtime reaction to config changes."""
        self._observers.append(observer)

    async def notify_changed(self, paths: frozenset[str]) -> None:
        """Fan out to every observer after a user edit of `paths` (dotted)."""
        for observer in self._observers:
            await observer.config_changed(self, paths)

    async def change_field(self, dotted: str, value: Any) -> bool:
        """The single user-edit write seam: set a dotted field, record it in
        `_declared`, and notify observers — only when the value actually
        changed (returns False on a no-op set). Internal writers that must
        stay silent (fetch_and_apply_model_info) use set_config_value directly."""
        old = set_config_value(self, dotted, value)
        if old == get_config_value(self, dotted):
            return False
        self._declared_fields.add(dotted)
        await self.notify_changed(frozenset({dotted}))
        return True

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
        """Decide the settings-source stack. argv is a constructor kwarg
        (init_settings carries the init kwargs): None → the real process argv,
        a list → that argv, [] → hermetic (explicit kwargs only)."""
        argv = init_settings.init_kwargs.get("cli_args")
        if argv == []:
            return (init_settings,)
        if argv is None:
            argv = sys.argv[1:]
        # `--config` belongs to the file source, not pydantic's CLI parser —
        # split it out so CliSettingsSource never sees a flag it would reject.
        config_paths, argv = _split_config_flags(argv)
        # Precedence high->low: CLI, env (SOLVEIG_*), then config files. pydantic
        # deep-merges nested models across sources and validates.
        cli = CliSettingsSource(
            settings_cls,
            cli_parse_args=argv,
            cli_shortcuts=_CLI_SHORTCUTS,
            **_CLI_OPTS,
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

    # ------------------------------------------------------------
    # Tool/Hook section schema
    # ------------------------------------------------------------
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
    def compose_core_tools(cls) -> None:
        """Build the `config.tools` section from the core tool list — one field per
        tool (`tool_name()` → its `config_model`) — so `config` never hand-enumerates
        core tools; adding a core tool needs no change here.

        Called once from `config/__init__.py` *after* the `SolveigConfig` re-export
        (the load order that lets each tool module resolve its top-level `from
        solveig.config import SolveigConfig`), and re-run only on a genuine
        tool-membership change — never per tool call."""
        from solveig.tools import CORE_TOOLS

        pairs = [(tool.tool_name(), tool.config_model) for tool in CORE_TOOLS]
        _compose_section(cls, "tools", pairs, "CoreToolsConfig")

    @classmethod
    def compose_plugin_tools(cls) -> None:
        """Build the `config.plugins.tools` section from the discovered plugin tools
        — the plugin parallel of `compose_core_tools`, and phase 2 of the two-phase
        bootstrap (parse → discover → compose → reparse). Reads each entry's config
        type via `config_model_of` (a `BaseTool` ClassVar or a callable's
        `@tool(config_model=…)` stash), so plugin config validates like core config.
        Rebuilds `SolveigConfig` too, since it embeds `PluginsConfig`."""
        from solveig.plugins.tools import (
            PLUGIN_TOOLS,
            config_model_of,
            plugin_tool_name,
        )

        pairs = [(plugin_tool_name(e), config_model_of(e)) for e in PLUGIN_TOOLS]
        _compose_section(
            PluginsConfig, "tools", pairs, "PluginToolsConfig", _MUTABLE_ALLOW
        )
        cls.model_rebuild(force=True)

    @classmethod
    def compose_plugin_hooks(cls) -> None:
        """Build the `config.plugins.hooks` section from the discovered hooks —
        the hook parallel of `compose_plugin_tools`. `config_by_hook` is
        `hooks_config_map()`'s deduped {hook_name: config_model}; a hook's
        config type is declared on the Hook class (`config_model`), defaulting
        to bare `ToolConfig` (enabled-only). Rebuilds `SolveigConfig` too,
        since it embeds `PluginsConfig`."""
        from solveig.plugins.hooks import hooks_config_map

        _compose_section(
            PluginsConfig,
            "hooks",
            list(hooks_config_map().items()),
            "PluginHooksConfig",
            _MUTABLE_ALLOW,
        )
        cls.model_rebuild(force=True)

    # ------------------------------------------------------------
    # Explicitly declared config fields
    # ------------------------------------------------------------
    def declared_config(self) -> dict[str, Any]:
        """The nested dict of only the explicitly-declared fields (file / CLI /
        `/config set`, tracked in `_declared`) — what `/config save` persists.
        Each declared path is copied out of `model_dump(mode="json")` (which
        applies the field serializers: key un-masked, enums → names, byte
        sizes → ints, command patterns → source strings)."""
        full = self.model_dump(mode="json")
        out: dict[str, Any] = {}
        for path in sorted(self._declared_fields):
            *parents, leaf = path.split(".")
            src: Any = full
            dest = out
            for part in parents:
                src = src[part]
                dest = dest.setdefault(part, {})
            dest[leaf] = src[leaf]
        return out

    def _record_declared(self) -> None:
        """Populate `_declared` with the dotted paths explicitly provided by the
        config file(s) and the command line (`cli_args`) — what `/config save`
        persists. Env-provided values are transient and intentionally excluded,
        as are `exclude=True` CLI-only fields (derived from the declaration,
        not a hand-kept name list)."""
        declared = _dict_to_dotted_leaves(sources.load_paths(self.config_files))
        argv = self.cli_args if self.cli_args is not None else sys.argv[1:]
        _, argv = _split_config_flags(argv)  # CliSettingsSource rejects --config
        if argv:
            cli: CliSettingsSource = CliSettingsSource(
                type(self),
                cli_parse_args=argv,
                cli_shortcuts=_CLI_SHORTCUTS,
                **_CLI_OPTS,
            )
            declared |= _dict_to_dotted_leaves(cli() or {})
        self._declared_fields = {
            path
            for path in declared
            if not type(self).model_fields[path.split(".", 1)[0]].exclude
        }

    # ------------------------------------------------------------
    # Entrypoint
    # ------------------------------------------------------------
    @classmethod
    async def parse_config_and_prompt(
        cls, cli_args: list[str] | None = None
    ) -> tuple[SolveigConfig, str, str | None]:
        # Compose the core tools section schema (known at init) and create a config
        # only for plugin discovery.
        cls.compose_core_tools()
        plugin_discovery_config = cls(cli_args=cli_args)

        from solveig.plugins import discover_plugins

        discover_plugins(plugin_discovery_config)

        # Re-compose the schema for the plugin section (tools + hooks). The second
        # parse validates plugin config against the real per-plugin models, the
        # same pipeline core config goes through.
        cls.compose_plugin_tools()
        cls.compose_plugin_hooks()
        cfg = cls(cli_args=cli_args)

        # config_files is already stamped (resolved paths) by ConfigFileSource.
        cfg._record_declared()
        for url in cfg.startup_mcp_servers:
            cfg.mcp.setdefault(url, MCPServerConfig(url=url))
        # TODO: consider returning just config, since the other fields are direct reads
        return cfg, cfg.prompt.strip(), cfg.resume
