"""Convert MCP tool definitions into BaseTool subclasses."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, create_model

from solveig.interface import SolveigInterface
from solveig.schema.result.base import ToolResult
from solveig.schema.tool.base import BaseTool

if TYPE_CHECKING:
    from mcp import ClientSession
    from mcp.types import Tool as MCPTool

    from solveig.config import SolveigConfig


class MCPToolResult(ToolResult):
    """Generic result for any MCP tool call.

    Title is not a Literal, so these results are not in the result_classes
    registry — session replay will fall back to base ToolResult for now.
    """

    title: str
    output: str | None = None

    async def _display_content(self, interface: SolveigInterface) -> None:
        if self.output:
            await interface.display_text_block(self.output, title="Output")


class _MCPToolBase(BaseTool):
    """Concrete intermediate base so create_model doesn't produce an abstract class.

    Methods are replaced per-tool by create_tool_class().
    """

    async def actually_solve(
        self, config: SolveigConfig, interface: SolveigInterface
    ) -> MCPToolResult:
        raise NotImplementedError

    def create_error_result(
        self, error_message: str, accepted: bool
    ) -> MCPToolResult:
        raise NotImplementedError

    @classmethod
    def get_description(cls) -> str:
        return cls.model_fields["title"].default or "MCP tool"


def _json_type(prop: dict) -> type:
    match prop.get("type", "string"):
        case "integer":
            return int
        case "number":
            return float
        case "boolean":
            return bool
        case "array":
            return list
        case "object":
            return dict
        case _:
            return str


def _schema_signature(input_schema: dict) -> str:
    """Build a parameter signature string from a JSON Schema object, e.g. '(a, b?, c)'."""
    required = set(input_schema.get("required", []))
    parts = [
        name if name in required else f"{name}?"
        for name in input_schema.get("properties", {})
    ]
    return f"({', '.join(parts)})" if parts else ""


def _schema_fields(input_schema: dict) -> dict[str, Any]:
    """Convert a JSON Schema object definition into pydantic create_model field specs."""
    fields: dict[str, Any] = {}
    required = set(input_schema.get("required", []))
    for name, prop in input_schema.get("properties", {}).items():
        python_type = _json_type(prop)
        description = prop.get("description", "")
        if name in required:
            fields[name] = (python_type, Field(..., description=description))
        else:
            fields[name] = (python_type | None, Field(None, description=description))
    return fields


def create_tool_class(mcp_tool: MCPTool, session: ClientSession) -> type[BaseTool]:
    """Create a concrete BaseTool subclass for a single MCP tool."""
    tool_name = mcp_tool.name
    description = mcp_tool.description or tool_name
    extra_fields = _schema_fields(mcp_tool.inputSchema or {})

    # Capture for closures
    _session = session
    _name = tool_name
    _fields = extra_fields

    async def actually_solve(
        self: _MCPToolBase,
        config: SolveigConfig,
        interface: SolveigInterface,
    ) -> MCPToolResult:
        arguments = {k: getattr(self, k) for k in _fields if getattr(self, k) is not None}
        try:
            result = await _session.call_tool(_name, arguments)
            output = "\n".join(
                block.text
                for block in result.content
                if hasattr(block, "text") and block.text
            )
            return MCPToolResult(
                tool=self, title=_name, accepted=True, output=output or None
            )
        except Exception as e:
            return MCPToolResult(
                tool=self, title=_name, accepted=False, error=str(e), output=None
            )

    def create_error_result(
        self: _MCPToolBase, error_message: str, accepted: bool
    ) -> MCPToolResult:
        return MCPToolResult(
            tool=self, title=_name, accepted=accepted, error=error_message, output=None
        )

    tool_class: type[BaseTool] = create_model(  # type: ignore[call-overload]
        tool_name,
        title=(Literal[tool_name], tool_name),  # type: ignore[valid-type]
        **extra_fields,
        __base__=_MCPToolBase,
    )
    tool_class.actually_solve = actually_solve  # type: ignore[attr-defined]
    tool_class.create_error_result = create_error_result  # type: ignore[attr-defined]
    sig = _schema_signature(mcp_tool.inputSchema or {})
    tool_class.get_description = classmethod(  # type: ignore[attr-defined]
        lambda cls, n=tool_name, s=sig, d=description: f"{n}{s}: {d}"
    )
    return tool_class
