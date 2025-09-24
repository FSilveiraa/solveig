import json
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from .. import SolveigConfig, utils
from ..llm import APIType
from .base import BaseSolveigModel
from .requirements import Requirement
from .results import RequirementResult


class BaseMessage(BaseSolveigModel):
    role: Literal["system", "user", "assistant"]
    comment: str = ""

    @field_validator("comment", mode="before")
    @classmethod
    def strip_comment(cls, comment):
        return (comment or "").strip()

    def to_openai(self) -> dict:
        data = self.model_dump()
        data.pop("role")
        return {
            "role": self.role,
            "content": json.dumps(data, default=utils.misc.default_json_serialize),
        }

    @property
    def token_count(self):
        return utils.misc.count_tokens(str(self))

    def __str__(self) -> str:
        return f"{self.role}: {self.to_openai()["content"]}"


class SystemMessage(BaseMessage):
    role: Literal["system"] = "system"

    def to_openai(self) -> dict:
        return {
            "role": self.role,
            "content": self.comment,
        }


# The user's message will contain
# - either the initial prompt or optionally more prompting
# - optionally the responses to results asked by the LLM
class UserMessage(BaseMessage):
    role: Literal["user"] = "user"
    results: list[RequirementResult] | None = None


# The LLM's response can be:
# - either a list of Requirements asking for more info
# - or a response with the final answer
# Note: This static class is kept for backwards compatibility but is replaced
# at runtime by get_filtered_assistant_message_class() which includes all active requirements
class AssistantMessage(BaseMessage):
    role: Literal["assistant"] = "assistant"
    requirements: list[Requirement] | None = (
        None  # Simplified - actual schema generated dynamically
    )


def get_filtered_assistant_message_class(
    config: SolveigConfig | None = None,
) -> type[BaseMessage]:
    """Get a dynamically created AssistantMessage class with only filtered requirements.

    This is used by Instructor to get the correct schema without caching issues.
    Gets all active requirements from the unified registry (core + plugins).

    Args:
        config: SolveigConfig instance for filtering requirements based on settings
    """
    # Get ALL active requirements from the unified registry
    try:
        from solveig.schema import REQUIREMENTS

        all_active_requirements = list(REQUIREMENTS.registered.values())
    except (ImportError, AttributeError):
        # Fallback - should not happen in normal operation
        all_active_requirements = []

    # Filter out CommandRequirement if commands are disabled
    if config and config.no_commands:
        from solveig.schema.requirements.command import CommandRequirement

        all_active_requirements = [
            req for req in all_active_requirements if req != CommandRequirement
        ]

    # Handle empty registry case
    if not all_active_requirements:
        # Return a minimal class if no requirements are registered
        class EmptyAssistantMessage(BaseMessage):
            requirements: list[Requirement] | None = None

        return EmptyAssistantMessage

    # Create union dynamically from all registered requirements
    if len(all_active_requirements) == 1:
        requirements_union: Any = all_active_requirements[0]
    else:
        # Create union using | operator (modern Python syntax)
        requirements_union = all_active_requirements[0]
        for req_type in all_active_requirements[1:]:
            requirements_union = requirements_union | req_type

    # Create completely fresh AssistantMessage class
    class AssistantMessage(BaseMessage):
        requirements: (
            list[
                Annotated[
                    requirements_union,  # type: ignore[valid-type]
                    Field(discriminator="title"),
                ]
            ]
            | None
        ) = None

    return AssistantMessage


# Type alias for any message type
Message = SystemMessage | UserMessage | AssistantMessage
UserMessage.model_rebuild()
AssistantMessage.model_rebuild()


@dataclass
class MessageHistory:
    system_prompt: str
    api_type: type[APIType.BaseAPI] = APIType.BaseAPI
    max_context: int = -1
    encoder: str | None = None  # TODO: this is not-great design, but it works
    messages: list[Message] = field(default_factory=list)
    message_cache: list[dict] = field(default_factory=list)

    def __post_init__(self):
        """Initialize with system message after dataclass init."""
        if not self.message_cache:  # Only add if not already present
            self.add_messages(SystemMessage(comment=self.system_prompt))

    def __iter__(self):
        """Allow iteration over messages: for message in message_history."""
        return iter(self.messages)

    def get_token_count(self) -> int:
        """Get total token count for the message cache using API-specific counting."""
        return sum(
            self.api_type.count_tokens(message["content"], self.encoder)
            for message in self.message_cache
        )

    def prune_message_cache(self):
        """Remove old messages to stay under context limit, preserving system message."""
        if self.max_context <= 0:
            return

        while self.get_token_count() > self.max_context and len(self.message_cache) > 1:
            # Always preserve the first message (system prompt) if possible
            if len(self.message_cache) > 1:
                # Remove the second message (oldest non-system message)
                self.message_cache.pop(1)
            else:
                break  # Can't remove system message

    def add_messages(
        self,
        *messages: Message,
    ):
        """Add a message and automatically prune if over context limit."""
        for message in messages:
            # message_container = MessageContainer(message)
            self.messages.append(message)
            self.message_cache.append(message.to_openai())
            self.prune_message_cache()

    def to_openai(self):
        return self.message_cache

    def to_example(self):
        return "\n".join(
            str(message) for message in self.messages if message.role != "system"
        )
