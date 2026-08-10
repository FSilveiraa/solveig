"""MCP (Model Context Protocol) client integration for Solveig.

This package `__init__` holds the connection record and the shared
`MCP_CONNECTIONS` dict, and nothing else. It is a dumb store: `client.py`
writes to it, `tools/available.py` reads it when deriving the active toolset,
and neither has to know the other exists. Nothing here announces a change —
the toolset is rebuilt from scratch each turn, so a connect or disconnect is
picked up on its own.

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
    """A connected MCP server: its config plus the toolset used to reach it.

    NOTE: carries no name of its own. `MCP_CONNECTIONS` is keyed by the server's
    name and `server_config.name` holds the same string, so a third copy on the
    record would be one more thing that can disagree — every reader here either
    already has the name in hand or is iterating `.items()`.
    """

    server_config: MCPServerConfig
    toolset: AbstractToolset
    """The filtered+prefixed toolset - entered/exited and placed in the
    combined agent toolset."""
    tool_names: list[str] = field(default_factory=list)
    """Snapshot of (post-filter, post-prefix) tool names from connect time."""

    @property
    def name(self) -> str:
        return self.server_config.name

    @property
    def url(self) -> str:
        return self.server_config.url


#: Connected servers, keyed by name — the same key `config.mcp` uses, so a
#: configured server and its live connection are the same entry in two dicts.
MCP_CONNECTIONS: dict[str, MCPConnection] = {}
