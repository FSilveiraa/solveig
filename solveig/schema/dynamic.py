"""
Handles the dynamic generation of Pydantic models and filtering of active requirements.
This logic is centralized here to avoid circular import issues.
"""
import json
from typing import cast, Union

from pydantic import Field, create_model

from solveig import SolveigConfig, utils
from solveig.plugins.schema import PLUGIN_REQUIREMENTS
from solveig.schema.requirement import CORE_REQUIREMENTS, Requirement, CommandRequirement
from solveig.schema.message.assistant import AssistantMessage


class CACHED_RESPONSE_MODEL:
    config_hash: str | None = None
    requirements_union: type[Requirement] | None = None
    message_class: type[AssistantMessage] | None = None


def _ensure_requirements_union_cached(config: SolveigConfig | None = None):
    """Internal helper to ensure requirements union is cached."""
    config_hash = str(hash(config.to_json(indent=None, sort_keys=True))) if config else ""

    if (
        config_hash == CACHED_RESPONSE_MODEL.config_hash
        and CACHED_RESPONSE_MODEL.requirements_union is not None
    ):
        return

    # Get the active requirements by combining the Core and (filtered) Plugin Requirements
    active_requirements: list[type[Requirement]] = list(CORE_REQUIREMENTS)
    active_requirements.extend(PLUGIN_REQUIREMENTS.active.values())

    # Apply config-based filters
    if config.no_commands:
        if CommandRequirement in active_requirements:
            active_requirements.remove(CommandRequirement)

    if not active_requirements:
        raise ValueError("No response model available for LLM to use: The active requirements list is empty.")

    requirements_union = cast(type[Requirement], Union[*active_requirements])

    CACHED_RESPONSE_MODEL.config_hash = config_hash
    CACHED_RESPONSE_MODEL.requirements_union = requirements_union
    CACHED_RESPONSE_MODEL.message_class = create_model(
        "DynamicAssistantMessage",
        requirements=(
            # HACK: I can't find a way to signal to Mypy "this is a Union[Requirement]" through a cast
            list[requirements_union] | None,  # type: ignore[valid-type]
            Field(None),
        ),
        __base__=AssistantMessage,
    )


def get_requirements_union(config: SolveigConfig | None = None) -> type[Requirement]:
    """Get the requirements union type with caching."""
    _ensure_requirements_union_cached(config)
    assert CACHED_RESPONSE_MODEL.requirements_union is not None
    return CACHED_RESPONSE_MODEL.requirements_union


def get_response_model(
    config: SolveigConfig | None = None,
) -> type[AssistantMessage]:
    """Get the AssistantMessage model with dynamic requirements field."""
    _ensure_requirements_union_cached(config)
    assert CACHED_RESPONSE_MODEL.message_class is not None
    return CACHED_RESPONSE_MODEL.message_class


def get_response_model_json(config):
    response_model = get_response_model(config)
    schema = response_model.model_json_schema()
    return json.dumps(schema, indent=2, default=utils.misc.default_json_serialize)