from __future__ import annotations

from typing import Any, Annotated

import anyconfig
from pydantic import (
    ByteSize,
    Field,
    model_validator, PlainSerializer,
)
from pydantic_settings import (
    CliPositionalArg,
)

from config import Config, ConfigDict
from config.sources import FILE_EXTENSIONS
from solveig.api.types import ApiConfig
from config.annotations.comma_list import CommaSeparated
from config.annotations.path import AbsolutePath, PathPattern
from solveig.interface.config import InterfaceConfig
from solveig.mcp_servers.config import MCPServerConfig, MCPConfig
from solveig.plugins.config import PluginsConfig
from solveig.session.config import SessionConfig
from solveig.system_prompt.config import SystemPromptConfig
from solveig.tools.core import CoreToolsConfig


class SolveigConfig(Config):
    model_config = ConfigDict(
        env_prefix="SOLVEIG_",
        cli_shortcuts={"config_files": ["c", "config"]},
        default_config_files = [
            f"{base}.{extension}"
            for base in ("~/.solveig/config", "./.solveig/config")
            for extension in FILE_EXTENSIONS
        ],
    )

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
