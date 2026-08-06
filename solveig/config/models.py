from __future__ import annotations

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
from solveig.api.types import APIType, OpenAI, resolve_api_type
from solveig.config import DEFAULT_SYSTEM_PROMPT

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


class ApiConfig(BaseModel):
    model_config = _MUTABLE
    url: str = Field(default="", description="LLM API endpoint URL")
    type: APIType = Field(
        default_factory=OpenAI,
        description="API provider type (openai, anthropic, gemini)",
    )

    @field_validator("type", mode="before")
    @classmethod
    def _parse_type(cls, v: Any) -> APIType:
        if isinstance(v, str):
            return resolve_api_type(v)
        return v

    @field_serializer("type")
    def _ser_type(self, v: APIType) -> str:
        return v.name

    # SecretStr so the key masks itself in repr/str/logs; the serializer un-masks
    # for /config save (secrecy is a property of the field, not of display code).
    key: SecretStr = Field(default=SecretStr(""), description="API authentication key")
    model: str | None = Field(
        default=None,
        description="LLM model identifier (e.g. gpt-4o, claude-sonnet-4-5)",
    )
    temperature: float = Field(default=0.0, description="Model temperature 0.0-2.0")
    max_context: int = Field(
        default=-1, description="Max context window in tokens (-1 = model's limit)"
    )
    timeout: float = Field(
        default=60.0, description="LLM API request timeout in seconds"
    )

    @field_serializer("key")
    def _ser_key(self, v: SecretStr) -> str:
        return v.get_secret_value()


class _ComposedSection(BaseModel):
    """Base for config sections built at runtime from a tool/hook list.
    Placeholder classes (CoreToolsConfig, PluginToolsConfig, …) subclass
    this; their real schema is injected by `_compose_section`. The
    TYPE_CHECKING `__getattr__` types untyped `config.tools.<name>` reads
    as `Any` at dev time; the typed path is a tool's `self.settings(config)`."""

    model_config = _MUTABLE

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...


class PreservingSection(_ComposedSection):
    """A composed section that KEEPS config for entries it has no field for.

    Used for the plugin sections: a block for a plugin absent on this machine
    round-trips through `/config save` instead of being stripped from a
    teammate's file.

    `model_extra` is pydantic's own storage and stays private to this class.
    Reaching into another model's `model_extra` from outside couples the caller
    to a storage detail; `undiscovered` says what the bucket MEANS here, which
    is the only thing any caller has ever wanted from it.
    """

    model_config = _MUTABLE_ALLOW

    @property
    def undiscovered(self) -> dict[str, Any]:
        """Config blocks kept for entries that were never discovered, by name -
        a typo, or a plugin missing on this machine. Not an error."""
        return dict(self.model_extra or {})


class CoreToolsConfig(_ComposedSection):
    """Placeholder for `config.tools` — composed from `CORE_TOOLS` at import
    time (`config/__init__._compose_core_tools()`), so a core tool's config
    validates like any other."""


class PluginToolsConfig(PreservingSection):
    """Placeholder for `config.plugins.tools` — composed from discovered
    plugin tools during the two-phase bootstrap, so a plugin tool's config
    validates like a core tool's."""


class PluginHooksConfig(PreservingSection):
    """Placeholder for `config.plugins.hooks` — composed from discovered hooks
    during the two-phase bootstrap, so a hook's config validates like a tool's.
    A hook's config type is declared on the Hook class (`config_model`)."""


class SystemPromptConfig(BaseModel):
    """The system-prompt category (distinct from top-level `briefing`)."""

    model_config = _MUTABLE
    content: str = Field(
        default=DEFAULT_SYSTEM_PROMPT, description="Raw system prompt template"
    )
    add_examples: bool = Field(
        default=False, description="Include few-shot examples in system prompt"
    )
    add_os_info: bool = Field(
        default=False, description="Include OS info in system prompt"
    )


class PluginsConfig(BaseModel):
    """`paths` = discovery dirs; `tools`/`hooks` = per-plugin config, both composed
    at runtime from the discovered plugins (empty placeholders until then, same as
    core's `config.tools`)."""

    model_config = _MUTABLE
    paths: list[str] = Field(
        default_factory=list, description="Plugin discovery directories"
    )
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


class SessionConfig(BaseModel):
    model_config = _MUTABLE
    dir: str = Field(
        default=".solveig/sessions", description="Directory for stored sessions"
    )
    auto_save: bool = Field(
        default=True, description="Auto-save the session after each response"
    )


class InterfaceConfig(BaseModel):
    model_config = _MUTABLE
    theme: themes.Palette = Field(
        default_factory=lambda: themes.DEFAULT_THEME, description="UI color theme"
    )
    code_theme: str = Field(
        default=themes.DEFAULT_CODE_THEME,
        description="Code syntax highlighting theme",
        # Choices declared on the FIELD (D0), read generically by the config
        # editor's prompt. Sorted at declaration; a future user-styles registry
        # changes this one line, not the editor.
        json_schema_extra={"choices": sorted(themes.CODE_THEMES)},
    )
    stream: bool = Field(
        default=True,
        description="Stream assistant output token-by-token as it's generated",
    )
    auto_collapse_tools: bool = Field(
        default=True, description="Auto-collapse tool groups after approval"
    )
    auto_copy_selection: bool = Field(
        default=True,
        description="Auto-copy click-drag selected text to clipboard on mouse release",
    )

    @field_validator("theme", mode="before")
    @classmethod
    def _parse_theme(cls, v: Any) -> Any:
        return themes.THEMES[v.strip().lower()] if isinstance(v, str) else v

    @field_serializer("theme")
    def _ser_theme(self, v: themes.Palette) -> str:
        return v.name
