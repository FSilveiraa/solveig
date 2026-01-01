"""
Handles the dynamic generation of Pydantic models and filtering of active tools.
This logic is centralized here to avoid circular import issues.
"""

from typing import Union, cast

from pydantic import Field, create_model

from solveig import SolveigConfig
from solveig.plugins.tools import PLUGIN_TOOLS
from solveig.schema.message.assistant import AssistantMessage
from solveig.schema.tool import (
    CORE_TOOLS,
    BaseTool,
    CommandTool,
)


class CACHED_RESPONSE_MODEL:
    config_hash: str | None = None
    tools_union: type[BaseTool] | None = None
    message_class: type[AssistantMessage] | None = None


def _ensure_tools_union_cached(config: SolveigConfig | None = None):
    """Internal helper to ensure tools union is cached."""
    config_hash = (
        str(hash(config.to_json(indent=None, sort_keys=True))) if config else ""
    )

    if (
        config_hash == CACHED_RESPONSE_MODEL.config_hash
        and CACHED_RESPONSE_MODEL.tools_union is not None
    ):
        return

    # Get the active tools by combining the Core and (filtered) Plugin tools
    active_tools: list[type[BaseTool]] = list(CORE_TOOLS)
    active_tools.extend(PLUGIN_TOOLS.active.values())

    # Apply config-based filters
    if config and config.no_commands:
        if CommandTool in active_tools:
            active_tools.remove(CommandTool)

    if not active_tools:
        raise ValueError(
            "No response model available for LLM to use: The active tools list is empty."
        )

    tools_union = cast(type[BaseTool], Union[*active_tools])

    CACHED_RESPONSE_MODEL.config_hash = config_hash
    CACHED_RESPONSE_MODEL.tools_union = tools_union
    CACHED_RESPONSE_MODEL.message_class = create_model(
        "DynamicAssistantMessage",
        tools=(
            # HACK: I can't find a way to signal to Mypy "this is a Union[BaseTool]" through a cast
            list[tools_union] | None,  # type: ignore[valid-type]
            Field(None),
        ),
        __base__=AssistantMessage,
    )


def get_tools_union(config: SolveigConfig | None = None) -> type[BaseTool]:
    """Get the tools union type with caching."""
    _ensure_tools_union_cached(config)
    assert CACHED_RESPONSE_MODEL.tools_union is not None
    return CACHED_RESPONSE_MODEL.tools_union


def get_response_model(
    config: SolveigConfig | None = None,
) -> type[AssistantMessage]:
    """Get the AssistantMessage model with dynamic tools field."""
    _ensure_tools_union_cached(config)
    assert CACHED_RESPONSE_MODEL.message_class is not None
    return CACHED_RESPONSE_MODEL.message_class
