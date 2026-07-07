"""Convert MCP tool definitions into pydantic-ai tool functions.

**Not yet ported to pydantic-ai native tool-calling** - this used to build
dynamic `BaseTool` (Pydantic model) subclasses for the old Instructor-based
architecture, which no longer exists. Phase 3 ("MCP integration", see
`ignore/project-logs/2026-07-04-18-34-pydantic-ai-migration.md`) replaces
this outright with pydantic-ai's own native MCP support
(`pydantic_ai.mcp`/`MCPServerStdio`/`MCPServerStreamableHTTP`, which compose
directly into a toolset) rather than hand-adapting JSON Schema into
dynamically-created tool functions here. Left as an explicit stub so
connecting to an MCP server fails loudly and clearly until then, instead of
silently misbehaving.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp import ClientSession
    from mcp.types import Tool as MCPTool


def create_tool_class(mcp_tool: MCPTool, session: ClientSession) -> Any:
    """Placeholder pending Phase 3's native pydantic-ai MCP integration."""
    raise NotImplementedError(
        f"MCP tool adapter for '{mcp_tool.name}' is not yet ported to "
        "pydantic-ai native tool-calling (Phase 3, planned)."
    )
