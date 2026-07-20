from __future__ import annotations

import fnmatch
import re
from typing import Any, Type

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

import solveig.interface.themes as themes
from solveig.api import APIType, parse_api_type

_MUTABLE = ConfigDict(validate_assignment=True, arbitrary_types_allowed=True)


class ApiConfig(BaseModel):
    model_config = _MUTABLE
    url: str = ""
    type: Type[APIType.BaseAPI] = APIType.OPENAI
    key: str = ""
    model: str | None = None
    temperature: float = 0.0
    max_context: int = -1
    timeout: float = 60.0

    @field_validator("type", mode="before")
    @classmethod
    def _parse_type(cls, v: Any) -> Any:
        return parse_api_type(v) if isinstance(v, str) else v

    @field_serializer("type")
    def _ser_type(self, v: Type[APIType.BaseAPI]) -> str:
        return v.name


class HttpConfig(BaseModel):
    model_config = _MUTABLE
    timeout: float = 10.0
    max_response_bytes: int = 50_000


class CommandConfig(BaseModel):
    model_config = _MUTABLE
    enabled: bool = True
    auto_execute: list[str] = Field(default_factory=list)

    @field_validator("auto_execute")
    @classmethod
    def _validate_regex(cls, patterns: list[str]) -> list[str]:
        for p in patterns:
            try:
                re.compile(p)
            except re.error as e:
                raise ValueError(f"Invalid regex in auto_execute: '{p}': {e}") from e
        return patterns


class ToolsConfig(BaseModel):
    model_config = _MUTABLE
    http: HttpConfig = Field(default_factory=HttpConfig)
    command: CommandConfig = Field(default_factory=CommandConfig)


class PluginsConfig(BaseModel):
    model_config = _MUTABLE
    paths: list[str] = Field(default_factory=list)
    enabled: dict[str, dict[str, Any]] = Field(default_factory=dict)


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
