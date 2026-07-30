from __future__ import annotations

from solveig.system_prompt import DEFAULT_SYSTEM_PROMPT

DEFAULT_CONFIG_PATHS: list[str] = [
    "./.solveig/config.yaml",
    "~/.solveig/config.yaml",
]

DEFAULT_PLUGIN_PATHS: list[str] = [
    "./.solveig/plugins",
    "~/.solveig/plugins",
]

from .config import (  # noqa: E402 — after the static defaults above so .config can import them back
    CLI_SETTINGS_OPTS,
    ConfigObserver,
    SolveigConfig,
    display_config_value,
)
from .models import MCPServerConfig  # noqa: E402

__all__ = [
    "CLI_SETTINGS_OPTS",
    "SolveigConfig",
    "ConfigObserver",
    "MCPServerConfig",
    "DEFAULT_CONFIG_PATHS",
    "DEFAULT_PLUGIN_PATHS",
    "DEFAULT_SYSTEM_PROMPT",
    "display_config_value",
]
