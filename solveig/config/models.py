from __future__ import annotations

import builtins
import fnmatch
from typing import TYPE_CHECKING, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_serializer,
    field_validator,
)

import solveig.interface.themes as themes
from solveig.api import APIType, parse_api_type

_MUTABLE = ConfigDict(validate_assignment=True, arbitrary_types_allowed=True)
# Like _MUTABLE but PRESERVES unknown keys as `model_extra` (extra="allow"). Used
# for the composed `plugins.tools` section so a config FILE's block for an
# undiscovered plugin round-trips through `/config save` instead of being dropped
# (which would strip a teammate's plugin config on a machine lacking that plugin)
# — surfaced as a warning at load, not an error. CLI stays strict (argparse rejects
# an unknown `--plugins.tools.foo.x` regardless, since it's not a defined flag).
_MUTABLE_ALLOW = ConfigDict(
    validate_assignment=True, arbitrary_types_allowed=True, extra="allow"
)

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


class ApiConfig(BaseModel):
    model_config = _MUTABLE
    url: str = ""
    type: builtins.type[APIType.BaseAPI] = APIType.OPENAI
    # SecretStr so the key masks itself in repr/str/logs; the serializer un-masks
    # for /config save (secrecy is a property of the field, not of display code).
    key: SecretStr = SecretStr("")
    model: str | None = None
    temperature: float = 0.0
    max_context: int = -1
    timeout: float = 60.0

    @field_validator("type", mode="before")
    @classmethod
    def _parse_type(cls, v: Any) -> Any:
        return parse_api_type(v) if isinstance(v, str) else v

    @field_serializer("type")
    def _ser_type(self, v: builtins.type[APIType.BaseAPI]) -> str:
        return v.name

    @field_serializer("key")
    def _ser_key(self, v: SecretStr) -> str:
        return v.get_secret_value()


class _ComposedSection(BaseModel):
    """Base for a config section whose real per-entry fields are composed at
    runtime from a tool list, not hand-enumerated here — `config.tools` (core
    tools, from `CORE_TOOLS`) and `config.plugins.tools` (plugin tools, from the
    discovered `PLUGIN_TOOLS`), both built by `SolveigConfig.compose_*()` in
    config.py. Adding a tool touches nothing here. The `TYPE_CHECKING` `__getattr__`
    types a direct `config.tools.<name>` read as Any (Any-style access stays
    available); the *typed* path is a tool's own `self.settings(config)`. The
    per-tool config type lives on each tool (`ToolConfig`/subclass in tools/)."""

    model_config = _MUTABLE

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...


class CoreToolsConfig(_ComposedSection):
    """Placeholder for `config.tools` — composed from `CORE_TOOLS` at import
    time (`config/__init__._compose_core_tools()`), so a core tool's config
    validates like any other."""


class PluginToolsConfig(_ComposedSection):
    """Placeholder for `config.plugins.tools` — composed from discovered
    plugin tools during the two-phase bootstrap, so a plugin tool's config
    validates like a core tool's."""


class PluginHooksConfig(_ComposedSection):
    """Placeholder for `config.plugins.hooks` — composed from discovered hooks
    during the same two-phase bootstrap, so a hook's config validates like a
    tool's. A hook is a function (no generic to auto-derive its config type from),
    so its schema comes from `@before/@after(config_model=…)` or bare `ToolConfig`."""


class SystemPromptConfig(BaseModel):
    """The system-prompt category (distinct from top-level `briefing`)."""

    model_config = _MUTABLE
    content: str = DEFAULT_SYSTEM_PROMPT
    add_examples: bool = False
    add_os_info: bool = False


class PluginsConfig(BaseModel):
    """`paths` = discovery dirs; `tools`/`hooks` = per-plugin config, both composed
    at runtime from the discovered plugins (empty placeholders until then, same as
    core's `config.tools`)."""

    model_config = _MUTABLE
    paths: list[str] = Field(default_factory=list)
    tools: PluginToolsConfig = Field(default_factory=PluginToolsConfig)
    hooks: PluginHooksConfig = Field(default_factory=PluginHooksConfig)


class MCPServerConfig(BaseModel):
    model_config = _MUTABLE
    url: str
    name: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    blocked_tools: list[str] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)
    timeout: float = 30.0

    def is_tool_allowed(self, tool_name: str) -> bool:
        if self.allowed_tools and not any(
            fnmatch.fnmatchcase(tool_name, p) for p in self.allowed_tools
        ):
            return False
        if self.blocked_tools and any(
            fnmatch.fnmatchcase(tool_name, p) for p in self.blocked_tools
        ):
            return False
        return True


class McpConfig(BaseModel):
    model_config = _MUTABLE
    servers: dict[str, MCPServerConfig] = Field(default_factory=dict)

    @field_validator("servers", mode="before")
    @classmethod
    def _normalize(cls, v: Any) -> Any:
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


class SessionConfig(BaseModel):
    model_config = _MUTABLE
    dir: str = ".solveig/sessions"
    auto_save: bool = True


class InterfaceConfig(BaseModel):
    model_config = _MUTABLE
    theme: themes.Palette = Field(default_factory=lambda: themes.DEFAULT_THEME)
    code_theme: str = themes.DEFAULT_CODE_THEME
    stream: bool = True
    auto_collapse_tools: bool = True
    auto_copy_selection: bool = True

    @field_validator("theme", mode="before")
    @classmethod
    def _parse_theme(cls, v: Any) -> Any:
        return themes.THEMES[v.strip().lower()] if isinstance(v, str) else v

    @field_serializer("theme")
    def _ser_theme(self, v: themes.Palette) -> str:
        return v.name
