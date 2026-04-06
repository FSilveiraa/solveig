"""
Single source of truth for which tools the LLM can use.

`AVAILABLE_TOOLS.rebuild(config)` must be called after any change to the active
tool set: plugin load/unload, MCP server connect/disconnect, or config mutations
that affect the tool set (e.g. toggling no_commands).
"""

from typing import Union, cast

from pydantic import Field, create_model

from solveig.config import SolveigConfig
from solveig.plugins.tools import PLUGIN_TOOLS
from solveig.schema.message.assistant import AssistantMessage
from solveig.schema.result.base import ToolResult
from solveig.schema.tool import CORE_TOOLS, BaseTool, CommandTool

# MCP tools are appended here when an MCP server connects, removed on disconnect.
# Call AVAILABLE_TOOLS.rebuild(config) after mutating.
MCP_TOOLS: list[type[BaseTool]] = []


def _collect_result_subclasses(cls: type[ToolResult]) -> list[type[ToolResult]]:
    """Recursively collect all ToolResult subclasses with a concrete title."""
    found = []
    for sub in cls.__subclasses__():
        if isinstance(sub.model_fields["title"].default, str):
            found.append(sub)
        found.extend(_collect_result_subclasses(sub))
    return found


class AvailableTools:
    """Holds the currently active tool set and Pydantic models derived from it."""

    def __init__(self) -> None:
        self._tools_union: type[BaseTool] | None = None
        self._response_model: type[AssistantMessage] | None = None
        self._result_classes: dict[str, type[ToolResult]] = {}

    def rebuild(self, config: SolveigConfig) -> None:
        """Recompute tools union, response model, and result classes from current sources."""
        active: list[type[BaseTool]] = (
            list(CORE_TOOLS) + list(PLUGIN_TOOLS.active.values()) + list(MCP_TOOLS)
        )

        if config.no_commands and CommandTool in active:
            active.remove(CommandTool)

        if not active:
            raise ValueError("No tools available: the active tools list is empty.")

        tools_union = cast(type[BaseTool], Union[*active])

        self._tools_union = tools_union
        self._response_model = create_model(
            "DynamicAssistantMessage",
            tools=(
                # HACK: no way to express dynamic Union[BaseTool] to mypy
                list[tools_union] | None,  # type: ignore[valid-type]
                Field(None),
            ),
            __base__=AssistantMessage,
        )
        self._result_classes = {
            sub.model_fields["title"].default: sub
            for sub in _collect_result_subclasses(ToolResult)
        }

    @property
    def tools_union(self) -> type[BaseTool]:
        assert self._tools_union is not None, (
            "Call rebuild() before accessing tools_union"
        )
        return self._tools_union

    @property
    def response_model(self) -> type[AssistantMessage]:
        assert self._response_model is not None, (
            "Call rebuild() before accessing response_model"
        )
        return self._response_model

    @property
    def result_classes(self) -> dict[str, type[ToolResult]]:
        return self._result_classes


AVAILABLE_TOOLS = AvailableTools()
