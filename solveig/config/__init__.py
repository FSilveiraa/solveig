from __future__ import annotations

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
