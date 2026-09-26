"""Defines all the available tools in the project."""
from typing import Any

from pydantic_ai import AbstractToolset, RunContext, ToolDefinition, CombinedToolset

from solveig.config import SolveigConfig
from solveig.context import SolveigContext
from solveig.mcp_servers import MCP_CONNECTIONS, MCPServerConfig
from solveig.tools.base import BaseTool
from solveig.tools.config import ToolConfig


def tool_classes(config: SolveigConfig) -> dict[str, type[BaseTool]]:
    """All available tool classes, including disabled tools, excluding MCP."""
    return {
        tool_name: tool_config.tool_class
        for tool_name, tool_config in (config.tools | config.plugins.tools)
        # TODO: find a way to express "config-of-type(s)", removing the need
        #  for this check
        if isinstance(tool_config, ToolConfig)
    }

def build_toolset(config: SolveigConfig) -> AbstractToolset:
    """All available tools, including disabled and MCP, expressed as pydantic-ai Toolset."""
    # === Core + Plugins ===
    core_and_plugin_toolsets: list[BaseTool] = [
        tool_class.as_tool() for tool_class in tool_classes(config).values()
    ]

    # === MCP ===
    # Each entry is the toolset available for one server connection
    mcp_toolsets: list[AbstractToolset] = []
    for server_name, server_connection in MCP_CONNECTIONS.items():
        server_config = config.mcp.get(server_name)
        # The simplest sync way to filter a toolset is `filtered`
        def _is_mcp_tool_active(
                _context: RunContext[SolveigContext],
                tool_definition: ToolDefinition,
                _server_name: str = server_name,
                _server_config: MCPServerConfig = server_config,
        ):
            return config.mcp.get(server_name).is_tool_allowed(tool_definition.name):
    mcp_toolsets.append(server_connection.toolset.filtered(_is_mcp_tool_active))

    return CombinedToolset(core_and_plugin_toolsets, *mcp_toolsets)

