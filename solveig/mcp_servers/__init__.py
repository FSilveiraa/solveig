"""MCP (Model Context Protocol) client integration for Solveig.

This package `__init__` deliberately holds the shared `MCP_CONNECTIONS` dict
and NOTHING else: `client.py` imports `AVAILABLE_TOOLS` (to trigger rebuilds
on connect/disconnect) while `tools/available.py` needs the same dict during
`rebuild()` — a top-level import of the dict from `client` there would cycle
(client -> available -> client). A dependency-free holder module both sides
can import is the established pattern for this (see the 2026-07-16 simplify
review); the package `__init__` plays that role, with no separate module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solveig.mcp_servers.client import MCPConnection

MCP_CONNECTIONS: dict[str, MCPConnection] = {}
