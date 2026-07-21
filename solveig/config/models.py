from __future__ import annotations

import builtins
import fnmatch
import re
import warnings
from typing import Any

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


class ToolConfig(BaseModel):
    """Base config every tool's config extends — carries the universal `enabled`
    flag (enabled-by-default). This is the declaration seam Sub-project B reuses
    for plugin tools/hooks; in A, the core tools below extend it statically."""

    model_config = _MUTABLE
    enabled: bool = True


class HttpConfig(ToolConfig):
    timeout: float = 10.0
    max_response_bytes: int = 50_000


class CommandConfig(ToolConfig):
    # Compiled patterns: pydantic validates each string into a re.Pattern (compiled
    # once, at parse time — invalid regexes are rejected declaratively) and
    # serializes them back to their source strings for /config save. "It's a regex"
    # is a property of the field, not something command.py re-derives per call.
    auto_execute: list[re.Pattern] = Field(default_factory=list)


# NOTE: the `copy` field below mirrors CopyTool's `tool_name()` and is required for
# `tools.copy.enabled` to line up with the tool registry. It deliberately shadows the
# deprecated `BaseModel.copy()` (we use `model_copy` everywhere), so we silence the
# one-time "shadows an attribute in parent" UserWarning pydantic raises at class build.
with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore", message=r'Field name "copy".*shadows', category=UserWarning
    )

    class ToolsConfig(BaseModel):
        """CORE tools only (static, known set). Every core tool has an entry so it
        can be disabled uniformly via `tools.<name>.enabled`. `command`/`http` carry
        extra fields; the rest are plain ToolConfig (just `enabled`)."""

        model_config = _MUTABLE
        command: CommandConfig = Field(default_factory=CommandConfig)
        http: HttpConfig = Field(default_factory=HttpConfig)
        read: ToolConfig = Field(default_factory=ToolConfig)
        write: ToolConfig = Field(default_factory=ToolConfig)
        edit: ToolConfig = Field(default_factory=ToolConfig)
        delete: ToolConfig = Field(default_factory=ToolConfig)
        # `copy` deliberately shadows deprecated BaseModel.copy (see NOTE above);
        # mypy sees the field/method type clash, hence the ignore.
        copy: ToolConfig = Field(default_factory=ToolConfig)  # type: ignore[assignment]
        move: ToolConfig = Field(default_factory=ToolConfig)
        tasks: ToolConfig = Field(default_factory=ToolConfig)


class SystemPromptConfig(BaseModel):
    """The system-prompt category (distinct from top-level `briefing`)."""

    model_config = _MUTABLE
    content: str = DEFAULT_SYSTEM_PROMPT
    add_examples: bool = False
    add_os_info: bool = False


class PluginsConfig(BaseModel):
    """In A: discovery dirs only. Plugins are discovered and on-by-default; per-plugin
    config (`plugins.tools.*`/`plugins.hooks.*`) is Sub-project B."""

    model_config = _MUTABLE
    paths: list[str] = Field(default_factory=list)


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
