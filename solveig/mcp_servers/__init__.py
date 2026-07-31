"""MCP (Model Context Protocol) client integration for Solveig.

This package `__init__` holds the connection record and the shared
`MCP_CONNECTIONS` dict, and nothing else: `client.py` imports `AVAILABLE_TOOLS`
(to trigger rebuilds on connect/disconnect) while `tools/available.py` needs the
same dict during `rebuild()` — a top-level import of either from `client` there
would cycle. A holder that imports only downward (config) is the established
pattern for this; the package `__init__` plays that role, with no separate
module.

`MCPConnection` lives here rather than in `client` so the dict can be typed
without an import guard — a `TYPE_CHECKING` import back into `client` would be
the same cycle, merely hidden from Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic_ai.toolsets import AbstractToolset

from solveig.config import MCPServerConfig


@dataclass
class MCPConnection:
    """A connected MCP server: its config plus the toolset used to reach it."""

    server_config: MCPServerConfig
    toolset: AbstractToolset
    """The filtered+prefixed toolset - entered/exited and placed in the
    combined agent toolset."""
    server_name: str | None = None
    """Server-reported name, captured once at connect time (server_info is
    only populated after __aenter__, and isn't worth keeping the raw
    MCPToolset around just to re-read later)."""
    tool_names: list[str] = field(default_factory=list)
    """Snapshot of (post-filter, post-prefix) tool names from connect time."""

    @property
    def url(self) -> str:
        return self.server_config.url

    @property
    def display_name(self) -> str:
        """User-configured name > server-reported name > URL."""
        return self.server_config.name or self.server_name or self.url


MCP_CONNECTIONS: dict[str, MCPConnection] = {}
