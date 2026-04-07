"""MCP (Model Context Protocol) client integration for Solveig."""

from .client import MCP_CONNECTIONS, connect, connect_all, disconnect

__all__ = ["MCP_CONNECTIONS", "connect", "connect_all", "disconnect"]
