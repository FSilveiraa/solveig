from __future__ import annotations

from typing import Any, Annotated

import anyconfig
from pydantic import (
    ByteSize,
    Field,
    field_serializer,
    field_validator,
    model_validator, PlainSerializer,
)
from pydantic_settings import (
    CliPositionalArg,
    SettingsConfigDict,
)

from config import Config
from config.sources import EXTENSIONS
from solveig.api.types import ApiConfig
from config.models import (
    DynamicSection,
    Path,
    ConfigSection,
    PreservingSection, CliFlags, CommaSeparated, PathPattern, AbsolutePath,
)
from solveig.interface.config import InterfaceConfig
from solveig.mcp_servers.config import MCPServerConfig, MCPConfig
from solveig.plugins.config import PluginsConfig
from solveig.session.config import SessionConfig
from solveig.system_prompt.config import SystemPromptConfig
from solveig.tools.core import CoreToolsConfig
from solveig.utils.file import Filesystem, SyncPath  # path normalization, not config I/O

__all__ = [
    "SolveigConfig",
    "ConfigSection",
    "DynamicSection",
    "PreservingSection",
]


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------


# def display_config_value(value: object, field_info: FieldInfo | None = None) -> str:
#     """Format a config value for display, driven by type and field name."""
#     choice = next(
#         (m for m in field_info.metadata if isinstance(m, Choice)),
#         None,
#     ) if field_info else None
#     if choice:
#         return choice.key(value)
#     if isinstance(value, SecretStr):
#         return "***" if value.get_secret_value() else "(not set)"
#     if isinstance(value, ByteSize):
#         return value.human_readable()
#     if isinstance(value, re.Pattern):
#         return value.pattern
#     if isinstance(value, list):
#         return ", ".join(display_config_value(v) for v in value) if value else "(empty)"
#     return repr(value)


# def _default_config_paths():
#     paths = []
#     for base in ("./.solveig/config", "~/.solveig/config"):
#         for extension in EXTENSIONS:
#             path = SyncPath(Filesystem.get_absolute_path(f"{base}.{extension}"))
#             if path.is_file():
#                 paths.append(path)
#     return paths


# TODO: isn't called, doesn't belong here, review
# def _compose_section(
#     target: type[BaseModel],
#     field_name: str,
#     pairs: list[tuple[str, type]],
#     model_name: str,
#     base: type[BaseModel] = DynamicSection,
# ) -> None:
#     """Build a composed model from (name, config_model) pairs and swap it into
#     `target.<field_name>` — one field per entry, so adding a tool/hook needs
#     no change here.
#
#     NOTE: the composed model SUBCLASSES the placeholder rather than copying its
#     `model_config`, so the section's semantics travel with it — plugin sections
#     inherit `PreservingSection` and keep both `extra="allow"` and the
#     `undiscovered` accessor. (pydantic forbids `__base__` and `__config__`
#     together, which is why the base carries the config.)
#     """
#     fields: dict[str, Any] = {
#         name: (config_model, Field(default_factory=config_model))
#         for name, config_model in pairs
#     }
#     with warnings.catch_warnings():
#         # HACK: `copy` (CopyTool) deliberately shadows the deprecated BaseModel.copy.
#         warnings.filterwarnings(
#             "ignore", message=r'Field name "copy".*shadows', category=UserWarning
#         )
#         composed = create_model(model_name, __base__=base, **fields)
#     target.model_fields[field_name].annotation = composed
#     target.model_fields[field_name].default_factory = composed
#     target.model_rebuild(force=True)


class SolveigConfig(Config):
    model_config = SettingsConfigDict(env_prefix="SOLVEIG_")

    # ------------------------------------------------------------
    # Persisted config fields
    # ------------------------------------------------------------
    api: ApiConfig = Field(default_factory=ApiConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    tools: CoreToolsConfig = Field(default_factory=CoreToolsConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    interface: InterfaceConfig = Field(default_factory=InterfaceConfig)
    system_prompt: SystemPromptConfig = Field(default_factory=SystemPromptConfig)
    briefing: CommaSeparated[AbsolutePath] = Field(
        default_factory=lambda: ["AGENTS.md"],
        description="Markdown files appended to the system prompt in order",
    )
    minimum_disk_space_left: Annotated[
        ByteSize,
        PlainSerializer(lambda v: v.human_readable())
    ] = Field(
        default=ByteSize(1024**3),  # 1 GiB
        description="Minimum free disk space before blocking writes",
    )
    auto_allowed_paths: CommaSeparated[PathPattern] = Field(
        default_factory=list,
        description="Glob patterns for auto-approved file paths",
    )
    ignored_paths: CommaSeparated[PathPattern] = Field(
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
    # Override from Config
    config_files: Annotated[list[Path], CliFlags("c", "config")] = Field(
        default_factory=lambda: [
            SyncPath(f"{base}.{extension}")
            for base in ("~/.solveig/config", "./.solveig/config")
            for extension in EXTENSIONS
        ],
        exclude=True,
    )

    prompt: CliPositionalArg[str] = Field(default="", exclude=True)
    resume: str | None = Field(default=None, exclude=True)  # --resume [name]
    # The CLI args this instance was booted from — always a list after
    # construction (never None). The source hook reads this as a constructor
    # kwarg: None → use sys.argv[1:], a list → use that, [] → hermetic.
    # parse_config_and_prompt stamps sys.argv[1:] when the kwarg was None,
    # so the field is a truthful durable record at every read site.

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(**kwargs)
        for url in self.startup_mcp_servers:
            server = MCPServerConfig.from_url(url)
            self.mcp.setdefault(server.name, server)

    # ------------------------------------------------------------
    # Pydantic overrides/validators
    # ------------------------------------------------------------

    # @field_validator("briefing", mode="before")
    # @classmethod
    # def _abs_briefing(cls, v: Any) -> Any:
    #     """Anchors the briefing paths to the starting directory"""
    #     return [str(Filesystem.get_absolute_path(p)) for p in v] if v else []

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

    @model_validator(mode="after")
    def _union_plugin_paths(self) -> SolveigConfig:
        """
        Each config file contributes their plugin discovery paths,
        but the merging overrides the value with the one from the highest-
        precedence file. This validator re-reads the config files and
        merges their plugin paths.
        """
        plugin_paths = set()
        for path in self.config_files:
            config_file = anyconfig.load(path)
            if isinstance(config_file, dict):
                for plugins_path in (
                        config_file
                        .get("plugins", {})
                        .get("paths", [])
                ):
                    plugin_paths.add(plugins_path)
        self.plugins.paths = list(plugin_paths)
        return self

    # @field_serializer("minimum_disk_space_left")
    # def _ser_min_disk(self, v: ByteSize) -> str:
    #     # Human-readable so a --full/--all config dump exports the default as
    #     # "1.0GiB" rather than 1073741824 (round-trips to the same value). The
    #     # /config save path grafts the exact original from _declared_fields, so
    #     # a user's "1GiB" is preserved verbatim there, not re-normalized here.
    #     return v.human_readable()


    # ------------------------------------------------------------
    # Tool/Hook section schema
    # ------------------------------------------------------------

    def is_tool_enabled(self, tool_name: str) -> bool:
        # The one home for "is this tool on?" — checks core tools, then
        # plugin tools, defaults to True for an unknown name.
        tools = self.tools
        if tool_name in type(tools).model_fields:
            return tools.get(tool_name).enabled
        plugin_tools = self.plugins.tools
        if tool_name in plugin_tools:
            return plugin_tools.tool_name.enabled
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

    # @classmethod
    # def parse(cls, cli_args: list[str] | None = None) -> SolveigConfig:
    #     """One pass over the layered sources (CLI > env > files), nothing more.
    #
    #     NOTE: the result is TRANSIENT. Startup uses it to read `plugins.paths`
    #     before the plugin schema exists, and drops it on the same line — the
    #     config that survives is the one `build()` returns, after composition.
    #     Anything that keeps a `parse()` result is holding an object whose plugin
    #     sections may no longer match the class, and whose observers nothing will
    #     ever notify. Use `build()`.
    #     """
    #     cfg = cls(cli_args=cli_args)
    #     if cfg.cli_args is None:
    #         cfg.cli_args = list(sys.argv[1:])
    #     return cfg
    #
    # @classmethod
    # def build(cls, cli_args: list[str] | None = None) -> SolveigConfig:
    #     """`parse()` plus the finishing touches for the config that is kept:
    #     declared-field tracking (what `/config save` persists) and startup MCP
    #     servers.
    #
    #     The two-phase dance around this (compose core tools → discover plugins
    #     → compose plugin sections → parse again) is startup sequencing and
    #     lives in `solveig.bootstrap`, above tools and plugins.
    #     """
    #     cfg = cls.parse(cli_args)
    #     # `--mcp-url` names a server only by address, so it gets the same derived
    #     # identifier an ad-hoc `/mcp connect <url>` would give it — and setdefault
    #     # means a config block already using that name wins, rather than the flag
    #     # silently replacing a configured server's allow/block lists.
    #     for url in cfg.startup_mcp_servers:
    #         # TODO: this should be absorbed some other way
    #         #  The fact that an MCP config is built from a URL is a fact
    #         #  that the MCP config class itself needs to express, not root.
    #         server = MCPServerConfig.from_url(url)
    #         cfg.mcp.setdefault(server.name, server)
    #     return cfg
