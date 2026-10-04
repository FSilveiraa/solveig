"""`plugins` — where to discover them, and a section per discovered plugin.

`tools` and `hooks` are empty by declaration for the same reason `config.tools`
is: their fields are one per discovered plugin, composed after discovery. They
PRESERVE unknown blocks, so config for a plugin absent on this machine survives
a `/config save` instead of being dropped.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from config.models import ConfigSection, DynamicSection
from solveig.tools.config import ToolConfig
from solveig.utils.file import Filesystem

DEFAULT_PLUGIN_PATHS: list[str] = [
    "./.solveig/plugins",
    "~/.solveig/plugins",
]


class HookConfig(ConfigSection):
    enabled: bool = Field(default=True, description="Enable this hook")


class PluginToolsConfig(DynamicSection[ToolConfig]):
    """
    `config.plugins.tools`: one entry per plugin tool. Each entry's type is the
    tool's own `config_model`, known only once the plugin is discovered, so
    entries wait as written until `resolve()` gives them their type.
    """

    _types_resolved_later = True


class PluginHooksConfig(DynamicSection[HookConfig]):
    """
    `config.plugins.hooks`: one entry per plugin hook. Each entry's type is the
    hook's own `config_model`, known only once the plugin is discovered, so
    entries wait as written until `resolve()` gives them their type.
    """

    _types_resolved_later = True


class PluginsConfig(ConfigSection):
    """`paths` = discovery dirs; `tools`/`hooks` = per-plugin config, both composed
    at runtime from the discovered plugins (empty placeholders until then, same as
    core's `config.tools`)."""

    # Directories where to discover plugins
    paths: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PLUGIN_PATHS),
        description="Plugin discovery directories",
        # The defaults are relative and must be anchored like any other value —
        # pydantic skips validation on a default unless told otherwise.
        validate_default=True,
    )
    # Plugin sub-sections
    # TODO: review plugin config structure, does the tools/hooks distinction still make sense,
    #  should we instead simplify by enabling/disabling everything under a plugin's file,
    #  or does an allow-by-default + per-tool disabling policy make more sense
    tools: PluginToolsConfig = Field(default_factory=PluginToolsConfig)
    hooks: PluginHooksConfig = Field(default_factory=PluginHooksConfig)

    @field_validator("paths", mode="before")
    @classmethod
    def _abs_paths(cls, _init_paths: Any) -> Any:
        """
        Ensures the plugin discovery directories are absolute paths when setting,
        so a `/plugins reload` after the assistant moved still scans the directories
        the user meant.
        """
        return (
            [str(Filesystem.get_absolute_path(path)) for path in _init_paths]
            if _init_paths
            else []
        )
