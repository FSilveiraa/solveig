from __future__ import annotations

import argparse
import re
import sys
import warnings
from collections.abc import Awaitable, Callable
from typing import Any

from anyio import Path
from pydantic import (
    BaseModel,
    ByteSize,
    Field,
    PrivateAttr,
    SecretStr,
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

from solveig.api.types import APIType
from solveig.config import DEFAULT_PLUGIN_PATHS, sources
from solveig.config.models import (
    ApiConfig,
    CoreToolsConfig,
    InterfaceConfig,
    MCPServerConfig,
    PluginsConfig,
    PreservingSection,
    SessionConfig,
    SystemPromptConfig,
    _ComposedSection,
)
from solveig.interface.themes import Palette
from solveig.utils import dotted
from solveig.utils.file import Filesystem  # path normalization, not config I/O
from solveig.utils.misc import CLI_SETTINGS_OPTS

__all__ = [
    "SolveigConfig",
]

# Options for CliSettingsSource — one home for how CLI parsing behaves across config
# boot, built-in subcommand parsing, and tool subcommand parsing.  "cli_avoid_json"
# is NOT here: the config boot path merges it on top (nested SolveigConfig fields
# need dotted flags), but subcommands parse flat models where it's a no-op.

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
    "startup_mcp_servers": "mcp-url",  # --mcp is taken by the mcp submodel
}


def _split_config_path_from_cli_args(
    argv: list[str],
) -> tuple[list[str], list[str]]:
    """Pull every `--config FILE` out of argv, returning (config_paths,
    remaining_argv). `--config` is consumed by the config-file source."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", action="append", dest="config", default=[])
    ns, rest = parser.parse_known_args(argv)
    return ns.config, rest


# An async callback (config, changed_paths) — registered via @config.on_change.
ConfigObserver = Callable[["SolveigConfig", frozenset[str]], Awaitable[None]]


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


def display_config_value(value: object) -> str:
    """Format a config value for display, driven by type — never by field name.
    Owned types (`APIType`, `Palette`) both carry a `name`; third-party types
    (SecretStr, ByteSize, re.Pattern) are dispatched below."""
    if isinstance(value, APIType | Palette):
        return value.name
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
    base: type[BaseModel] = _ComposedSection,
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


class SolveigConfig(BaseSettings):
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
        validate_assignment=True,
        arbitrary_types_allowed=True,
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
    # FIXED: defaulted to DEFAULT_CONFIG_PATHS, which is the SEARCH LIST (with
    # an unexpanded `~`), not files that were loaded. On a machine with no
    # config file — or any path where ConfigFileSource doesn't run — the default
    # survived and `_record_declared` tried to open a literal `<cwd>/~/.solveig/
    # config.yaml`, crashing startup. "Nothing loaded" is [].
    config_files: list[str] = Field(default_factory=list, exclude=True)
    resume: str | None = Field(default=None, exclude=True)  # --resume [name]
    startup_mcp_servers: list[str] = Field(
        default_factory=list, exclude=True
    )  # use `--mcp-url URL`
    # The CLI args this instance was booted from — always a list after
    # construction (never None). The source hook reads this as a constructor
    # kwarg: None → use sys.argv[1:], a list → use that, [] → hermetic.
    # parse_config_and_prompt stamps sys.argv[1:] when the kwarg was None,
    # so the field is a truthful durable record at every read site.
    cli_args: list[str] | None = Field(default=None, exclude=True)

    # ------------------------------------------------------------
    # Runtime fields (unpersisted)
    # ------------------------------------------------------------
    # dotted paths explicitly set via file/CLI/`/config set` — what /config save persists
    _declared_fields: set[str] = PrivateAttr(default_factory=set)
    # observers for field changes: (callback, paths_filter | None)
    _observers: list[tuple[ConfigObserver, frozenset[str] | None]] = PrivateAttr(
        default_factory=list
    )

    # ------------------------------------------------------------
    # Config change observers — @config.on_change(*paths) decorator
    # ------------------------------------------------------------

    async def notify_changed(self, paths: frozenset[str]) -> None:
        """Notify all observers, filtered by registered config path.

        NOTE: iterates a COPY — a handler is allowed to register another
        observer (a reloaded plugin module doing so at import is the live case),
        and mutating the list mid-iteration would raise.

        NOTE: a handler that mutates the schema it is being notified about (e.g.
        recomposing `plugins.tools` in response to `plugins.paths`) changes the
        shape of the object described by the very notification in flight. Rare
        enough to document rather than engineer around; if it spreads, the
        answer is to defer the recomposition, not to reorder this loop.

        NOTE: handlers are isolated from each other — one that raises no longer
        cancels the ones after it. Plugin reload subscribes here, so a handler
        now runs filesystem I/O and arbitrary plugin code; without isolation one
        bad plugin would stop the stats bar and the theme from updating. The
        failures are re-raised together afterwards rather than swallowed: every
        observer gets its turn AND nothing goes quiet.
        """
        failures: list[Exception] = []
        for handler, filter_paths in list(self._observers):
            # An observer that named no paths hears about everything. One that
            # did hears only its own matches — which may be exact
            # (`api.url`) or a whole section (`api`, `tools.http`).
            paths_to_notify = (
                frozenset(
                    path
                    for path in paths
                    if any(dotted.matches_prefix(path, p) for p in filter_paths)
                )
                if filter_paths
                else paths
            )
            if paths_to_notify:
                try:
                    await handler(self, paths_to_notify)
                except Exception as e:  # noqa: BLE001 - isolation, see above
                    failures.append(e)
        if failures:
            raise ExceptionGroup("config observers failed", failures)

    def on_change(self, *paths: str) -> Callable[[ConfigObserver], ConfigObserver]:
        """Decorator: register a callback for the given dotted *paths, which may
        be exact fields or section prefixes. Empty *paths means every change::

            @config.on_change("api.model", "api.url")
            async def _on_api_change(config, paths): ...

        Typed against `ConfigObserver` so a mis-shaped handler is a type error
        where it is written, rather than a TypeError inside an await later.
        """
        filt = frozenset(paths) if paths else None

        def register(fn: ConfigObserver) -> ConfigObserver:
            self._observers.append((fn, filt))
            return fn

        return register

    def unresolved_paths(self) -> dict[str, list[str]]:
        """Subscribed paths that currently reach nothing, keyed by handler.

        Derived, never stored: the answer depends on the schema as it stands
        right now, and the schema changes when plugins are discovered or
        reloaded. Computing it on demand means a subscription to a not-yet-
        installed plugin reports as unresolved and then quietly stops doing so
        once the plugin arrives — with no invalidation hook to forget.

        A section counts as resolved: subscribing to `api` is legitimate.
        """
        out: dict[str, list[str]] = {}
        for handler, filter_paths in self._observers:
            if not filter_paths:
                continue
            missing = sorted(p for p in filter_paths if not dotted.resolves(self, p))
            if missing:
                name = (
                    f"{handler.__module__}.{getattr(handler, '__qualname__', handler)}"
                )
                out.setdefault(name, []).extend(missing)
        return out

    def get(self, path: str) -> Any:
        obj, leaf = dotted.owner_of(self, path)
        return getattr(obj, leaf)

    async def set(self, path: str, value: Any, *, notify: bool = True) -> bool:
        """The single user-edit write seam.  Record in *_declared* and — when
        the value actually changed — notify observers.  Pass *notify=False* for
        internal writes (e.g. max_context from a model-fetch) that must be
        visible but shouldn't re-trigger dependent observers."""
        obj, leaf = dotted.owner_of(self, path)
        old = getattr(obj, leaf)
        setattr(obj, leaf, value)
        new = getattr(obj, leaf)
        if old == new:
            return False
        self._declared_fields.add(path)
        if notify:
            await self.notify_changed(frozenset({path}))
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
            cli_shortcuts=_CLI_SHORTCUTS,
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
    # Runtime schema composition
    # ------------------------------------------------------------
    # Config knows HOW to build these sections — it owns the models and the
    # mutability rules. It does not know WHAT goes in them: the caller supplies
    # (name, config_model) pairs. That keeps config from importing tools or
    # plugins, which sit above it. `solveig.bootstrap` gathers the pairs.

    @classmethod
    def compose_tools(cls, pairs: list[tuple[str, type]]) -> None:
        """Build `config.tools` — one field per core tool, so adding a core
        tool needs no change here."""
        _compose_section(cls, "tools", pairs, "CoreToolsConfig")

    @classmethod
    def compose_plugin_tools(cls, pairs: list[tuple[str, type]]) -> None:
        """Build `config.plugins.tools` — the plugin parallel of
        `compose_tools`. Each entry's config type is a declared field (BaseTool
        generic arg or FunctionTool.config_model), so plugin config validates
        like core config."""
        _compose_section(
            PluginsConfig, "tools", pairs, "PluginToolsConfig", PreservingSection
        )
        cls.model_rebuild(force=True)

    @classmethod
    def compose_plugin_hooks(cls, pairs: list[tuple[str, type]]) -> None:
        """Build `config.plugins.hooks` — the hook parallel of
        `compose_plugin_tools`. A hook's config type comes from its
        `@before_tool/@after_tool(config_model=…)`, defaulting to bare `ToolConfig`."""
        _compose_section(
            PluginsConfig,
            "hooks",
            pairs,
            "PluginHooksConfig",
            PreservingSection,
        )
        cls.model_rebuild(force=True)

    def rebuild_plugin_sections(self) -> None:
        """Re-validate the live plugin sections against the classes a recompose
        just installed. Call after `compose_plugin_tools`/`compose_plugin_hooks`
        on an already-built config — i.e. on a plugin reload; startup composes
        before anything is built and needs this not at all.

        Recomposition swaps the CLASS behind `plugins.tools`/`plugins.hooks`, so
        a live instance keeps holding objects of the previous class. The fix is
        NOT to build a fresh SolveigConfig: every `@config.on_change` observer
        is registered against this object, and replacing it would leave them
        subscribed to a corpse. So the sections are rebuilt and `self` survives.

        Dumping and re-validating carries the configured values across and
        routes a block whose plugin just disappeared into `model_extra`, where
        PRESERVE keeps it for `/config save`.
        """
        for section in ("tools", "hooks"):
            composed = PluginsConfig.model_fields[section].annotation
            assert composed is not None  # just installed by _compose_section
            current = getattr(self.plugins, section)
            setattr(self.plugins, section, composed(**current.model_dump()))

    # ------------------------------------------------------------
    # Explicitly declared config fields
    # ------------------------------------------------------------

    def declared_config(self) -> dict[str, Any]:
        """The nested dict of only the explicitly-declared fields (file / CLI /
        `/config set`, tracked in `_declared`) — what `/config save` persists.
        Each declared path is copied out of `model_dump(mode="json")` (which
        applies the field serializers: key un-masked, enums → names, byte
        sizes → ints, command patterns → source strings).

        NOTE: a declared path whose plugin is not installed still lands here —
        `PreservingSection` keeps the block and it dumps like any other value.
        So `MissingPath` out of this loop is not "plugin absent", it is
        "preservation failed and this value is about to be lost", which is why
        it propagates instead of being skipped. `/config save` reports it.
        """
        full = self.model_dump(mode="json")
        out: dict[str, Any] = {}
        for path in sorted(self._declared_fields):
            dotted.graft(out, path, dotted.extract(full, path))
        return out

    def _record_declared(self) -> None:
        """Populate `_declared` with the dotted paths explicitly provided by the
        config file(s) and the command line (`cli_args`) — what `/config save`
        persists. Excludes env vars and CLI-only fields (`exclude=True`)"""
        declared = dotted.to_leaves(sources.load_paths(self.config_files))
        if self.cli_args is not None:
            _, argv = _split_config_path_from_cli_args(
                self.cli_args
            )  # CliSettingsSource rejects --config
            if argv:
                cli: CliSettingsSource = CliSettingsSource(
                    type(self),
                    cli_parse_args=argv,
                    cli_shortcuts=_CLI_SHORTCUTS,
                    **CLI_SETTINGS_OPTS,
                    cli_avoid_json=True,
                )
                declared |= dotted.to_leaves(cli() or {})
        self._declared_fields = {
            path
            for path in declared
            if not type(self).model_fields[path.split(".", 1)[0]].exclude
        }

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
        # config_files is already stamped (resolved paths) by ConfigFileSource.
        cfg._record_declared()
        for url in cfg.startup_mcp_servers:
            cfg.mcp.setdefault(url, MCPServerConfig(url=url))
        return cfg
