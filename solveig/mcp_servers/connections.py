"""Live MCP connections registry.

Kept in its own dependency-free module so both `mcp_servers.client` (which
imports `AVAILABLE_TOOLS` at module level to trigger rebuilds on
connect/disconnect) and `tools.available` (which reads this registry during
`rebuild()`) can import it at module top level without an import cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solveig.mcp_servers.client import MCPConnection

MCP_CONNECTIONS: dict[str, MCPConnection] = {}
