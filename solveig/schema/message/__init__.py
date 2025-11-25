import json
from typing import Union, cast

from pydantic import Field, create_model

from solveig import SolveigConfig, utils
from solveig.schema import REQUIREMENTS, Requirement
from solveig.schema.message.assistant import AssistantMessage
from solveig.schema.message.message_history import MessageHistory
from solveig.schema.message.system import SystemMessage
from solveig.schema.message.user import UserComment, UserMessage

UserMessage.model_rebuild()
AssistantMessage.model_rebuild()


class CACHED_RESPONSE_MODEL:
    config_hash: str | None = None
    requirements_union: type[Requirement] | None = None
    message_class: type[AssistantMessage] | None = None


def _ensure_requirements_union_cached(config: SolveigConfig | None = None):
    """Internal helper to ensure requirements union is cached."""
    # Generate config hash for caching
    config_hash = None
    if config:
        config_hash = str(hash(config.to_json(indent=None, sort_keys=True)))

    # Return early if cache is still valid
    if (
        config_hash == CACHED_RESPONSE_MODEL.config_hash
        and CACHED_RESPONSE_MODEL.requirements_union is not None
    ):
        return

    # Get ALL active requirements from the unified registry
    try:
        all_active_requirements: list[type[Requirement]] = list(
            REQUIREMENTS.registered.values()
        )
    except (ImportError, AttributeError):
        all_active_requirements = []

    # Filter out CommandRequirement if commands are disabled
    if config and config.no_commands:
        from solveig.schema.requirement.command import CommandRequirement

        all_active_requirements = [
            req for req in all_active_requirements if req != CommandRequirement
        ]

    # Handle empty registry case
    if not all_active_requirements:
        raise ValueError("No response model available for LLM to use")

    # Create a Union of all requirement types
    requirements_union = cast(type[Requirement], Union[*all_active_requirements])

    # Cache the result and clear dependent cache
    CACHED_RESPONSE_MODEL.config_hash = config_hash
    CACHED_RESPONSE_MODEL.requirements_union = requirements_union

    assert CACHED_RESPONSE_MODEL.requirements_union is not None, (
        "Union should not be None"
    )

    CACHED_RESPONSE_MODEL.message_class = create_model(
        "DynamicAssistantMessage",
        requirements=(
            list[CACHED_RESPONSE_MODEL.requirements_union] | None,  # type: ignore[valid-type]
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


__all__ = [
    "MessageHistory",
    "SystemMessage",
    "UserMessage",
    "UserComment",
    "AssistantMessage",
    "get_requirements_union",
    "get_response_model",
]
