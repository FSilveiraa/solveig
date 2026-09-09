"""Solveig's own config sections — what the app actually has to configure.

`models.py` beside this file is the FRAMEWORK these are built from
(`ConfigSection`, `Choice`, the mutability rules) and knows none of them. The
dependency is one-way on purpose: a section names the framework, never the
reverse, which is what lets a section move to the module that owns its choices
(`ApiConfig` -> `solveig.api`, `TuiConfig` -> the TUI) without a cycle. That
cycle is exactly what a shared module caused before the split.
"""

from __future__ import annotations

import fnmatch
import re
import shlex
from typing import Any
from urllib.parse import urlparse

from pydantic import Field, field_validator

from solveig.config import DEFAULT_SYSTEM_PROMPT
from solveig.config.models import (
    ComposedConfigSection,
    ConfigSection,
    PreservingConfigSection,
)
from solveig.interface.tui import TuiConfig
from solveig.utils.file import Filesystem

# An MCP server name is announced to the model as `<name>_<tool>`, so it is held
# to the charset tool names are allowed across providers — letters, digits, `_`
# and `-`. Notably NOT `.`, which every dotted-path language in this tree treats
# as a separator.
_MCP_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


class CoreToolsConfig(ComposedConfigSection):
    """
    Placeholder for `config.tools` — composed from `CORE_TOOLS`.
    Tools declare config types at class declaration (MyTool(BaseTool[MyConfig])).
    """


class PluginToolsConfig(PreservingConfigSection):
    """
    Placeholder for `config.plugins.tools` — composed from discovered plugin tools
    Tools declare config types at class declaration (MyTool(BaseTool[MyConfig])).
    """


class PluginHooksConfig(PreservingConfigSection):
    """
    Placeholder for `config.plugins.hooks` — composed from discovered plugin hooks.
    Hooks declare config types through their class's `config_model`
    """


class SystemPromptConfig(ConfigSection):
    """The system-prompt category (distinct from top-level `briefing`)."""

    # TODO: review briefing config, confirm whether integration into this section would make sense

    content: str = Field(
        default=DEFAULT_SYSTEM_PROMPT, description="Raw system prompt template"
    )
    add_examples: bool = Field(
        default=False, description="Include few-shot examples in system prompt"
    )
    add_os_info: bool = Field(
        default=False, description="Include OS info in system prompt"
    )


class PluginsConfig(ConfigSection):
    """`paths` = discovery dirs; `tools`/`hooks` = per-plugin config, both composed
    at runtime from the discovered plugins (empty placeholders until then, same as
    core's `config.tools`)."""

    # Directories where to discover plugins
    paths: list[str] = Field(
        default_factory=list, description="Plugin discovery directories"
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


class MCPServerConfig(ConfigSection):
    """
    Config section for one MCP server.

    MCP servers are identified by `name`, `url` is only an address. `name` should remain
    the key for `config.mcp.<server>` and `MCP_CONNECTIONS`, and is the prefix of each
    of the server's tools announced to the agent (`<name>_<tool>`).

    """

    # TODO: review `name` with `exclude=True`, reasoning makes sense, but deserves revisiting
    #  and at least pinning with a test. In which situations is an MCP config even disagreeing
    #  about being dict vs model? Is re-deriving an MCP server's name a necessary thing?

    name: str = Field(
        # exclude=True` is necessary since `SolveigConfig._normalize_mcp` re-creates the value
        # at runtime, replaces it here and indexes the config entry by it. If this section's `name`
        # changed on re-creation, when it got exported to a file this entry would have a different
        # name (ex: `[mcp.parallel]` -> `[mcp.parallel_search]`)
        exclude=True
    )
    url: str
    allowed_tools: list[str] = Field(default_factory=list)
    blocked_tools: list[str] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)
    # TODO: review whether headers are relevant, usable and anywhere near industry standard in configs
    timeout: float = Field(
        default=30.0,
        # TODO: consider tying an MCP's connection timeout to their own tool's execution timeout
    )

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        """
        An MCP server's name can be used by subcommands and CLI args, so it needs to
        respect the charset tool names allow and ensure it doesn't conflict with the
        dotted-path notation used by `config set`
        """
        if not _MCP_NAME.match(v):
            raise ValueError(
                f"MCP server name {v!r} is not a valid identifier. "
                "Server names may use letters, digits, '_' and '-'."
            )
        return v

    @classmethod
    def from_url(cls, url: str, name: str = "") -> MCPServerConfig:
        """
        Produces an MCP config from a URL.
        If `name` is not given, the URL is parsed into a name usable by subcommands
        and dotted config paths.
        """
        if not name:
            if url.startswith("stdio://"):
                base = shlex.split(url[len("stdio://") :])[0].rsplit("/", 1)[-1]
            else:
                base = urlparse(url).hostname or url
            name = re.sub(r"[^a-zA-Z0-9_-]+", "_", base).strip("_") or "mcp"
        return cls(name=name, url=url)

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Determines if an MCP server's announced tool can be used."""
        # TODO: review/clarify usage of fnmatch
        if self.allowed_tools and not any(
            fnmatch.fnmatchcase(tool_name, p) for p in self.allowed_tools
        ):
            return False
        if self.blocked_tools and any(
            fnmatch.fnmatchcase(tool_name, p) for p in self.blocked_tools
        ):
            return False
        return True


class SessionConfig(ConfigSection):
    """Config section for the session manager."""

    path: str = Field(
        default=".solveig/sessions/",
        description="Directory for stored sessions",
        # TODO: consider renaming, "path" sounds like it could name a single file.
        #  Maybe it should be an acceptable edge case: if the user names a session file,
        #  use that as the single session, otherwise use it as a session storage dir
    )
    auto_save: bool = Field(
        default=True, description="Auto-save the session after each response"
    )

    @field_validator("path", mode="before")
    @classmethod
    def _abs_path(cls, _path: Any) -> Any:
        """`SessionManager.sessions_dir` re-reads this on every access, so the
        default `.solveig/sessions` would follow the assistant around and scatter
        a single conversation's files across whatever directories it visited."""
        return str(Filesystem.get_absolute_path(_path)) if _path else _path


class WebConfig(ConfigSection):
    """Settings only a browser frontend can honour. Nothing serves these yet -
    they are here because they are what makes `interface.tui` a section rather
    than a prefix: the two frontends have genuinely disjoint knobs."""

    host: str = Field(default="127.0.0.1", description="Address to serve the web UI on")
    port: int = Field(default=8080, description="Port to serve the web UI on")


class BroadcastConfig(ConfigSection):
    """
    Configuration for the broadcast interface.
    When enabled (default), allows the agent to run in a daemon in the background,
    using the BroadcastInterface to handle concurrent connections over a single session
    """

    enabled: bool = Field(
        default=True,
        description="Run agent as daemon, broadcast to connected interfaces",
    )
    socket: str = "/tmp/solveig.socket"
    # TODO: make PathLike, see config path fields
    # timeout: int = Field(default=30)
    # TODO: consider whether a timeout makes sense for the broadcast interface


class InterfaceConfig(ConfigSection):
    """
    Contains each interface's configuration, plus the broadcast settings and
    general visual configuration.
    """

    broadcast: BroadcastConfig = Field(default_factory=BroadcastConfig)
    tui: TuiConfig = Field(default_factory=TuiConfig)
    web: WebConfig = Field(default_factory=WebConfig)
