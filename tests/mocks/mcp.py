"""Minimal MCP server for local testing and integration tests.

Run directly to start the server:
    python tests/mocks/mcp.py

Then connect from Solveig:
    /mcp connect http://127.0.0.1:8000/mcp
"""

from fastmcp import FastMCP

mcp = FastMCP("solveig-test")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


@mcp.tool()
def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"


@mcp.tool()
def echo(message: str) -> str:
    """Echo a message back."""
    return message


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8001)
