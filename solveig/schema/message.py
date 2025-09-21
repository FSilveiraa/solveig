import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from .. import utils
from ..llm import APIType
from .requirements import Requirement
from .results import RequirementResult

# Requirements imported dynamically from registry to support plugins


class BaseMessage(BaseModel):
    comment: str = ""

    def to_openai(self) -> str:
        return json.dumps(self.model_dump(), default=utils.misc.default_json_serialize)

    @field_validator("comment", mode="before")
    @classmethod
    def strip_comment(cls, comment):
        return (comment or "").strip()


class SystemMessage(BaseMessage):
    def to_openai(self):
        return self.comment


# The user's message will contain
# - either the initial prompt or optionally more prompting
# - optionally the responses to results asked by the LLM
class UserMessage(BaseMessage):
    results: list[RequirementResult] | None = None

    def to_openai(self) -> str:
        data = self.model_dump()
        data["results"] = (
            [result.to_openai() for result in self.results]
            if self.results is not None
            else None
        )
        return json.dumps(data, default=utils.misc.default_json_serialize)


# The LLM's response can be:
# - either a list of Requirements asking for more info
# - or a response with the final answer
# Note: This static class is kept for backwards compatibility but is replaced
# at runtime by get_filtered_llm_message_class() which includes all active requirements
class LLMMessage(BaseMessage):
    requirements: list[Requirement] | None = (
        None  # Simplified - actual schema generated dynamically
    )


def get_filtered_llm_message_class():
    """Get a dynamically created LLMMessage class with only filtered requirements.

    This is used by Instructor to get the correct schema without caching issues.
    Gets all active requirements from the unified registry (core + plugins).
    """
    # Get ALL active requirements from the unified registry
    try:
        from solveig.schema import REQUIREMENTS

        all_active_requirements = list(REQUIREMENTS.registered.values())
    except (ImportError, AttributeError):
        # Fallback - should not happen in normal operation
        all_active_requirements = []

    # Handle empty registry case
    if not all_active_requirements:
        # Return a minimal class if no requirements are registered
        class EmptyLLMMessage(BaseMessage):
            requirements: list[Requirement] | None = None

        return EmptyLLMMessage

    # Create union dynamically from all registered requirements
    if len(all_active_requirements) == 1:
        requirements_union = all_active_requirements[0]
    else:
        requirements_union = all_active_requirements[0]
        for req_type in all_active_requirements[1:]:
            requirements_union = requirements_union | req_type

    # Create completely fresh LLMMessage class
    class FilteredLLMMessage(BaseMessage):
        requirements: (
            list[
                Annotated[
                    requirements_union,
                    Field(discriminator="title"),
                ]
            ]
            | None
        ) = None

    return FilteredLLMMessage


@dataclass
class MessageContainer:
    message: BaseMessage
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    role: Literal["user", "assistant", "system"] = field(init=False)

    def __init__(
        self,
        message: BaseMessage,
        role: Literal["user", "assistant", "system"] | None = None,
    ):
        self.message = message
        if role:
            self.role = role
        elif isinstance(message, UserMessage):
            self.role = "user"
        elif isinstance(message, SystemMessage):
            self.role = "system"
        elif hasattr(message, "requirements"):
            # Handle dynamically created LLMMessage classes
            self.role = "assistant"
        else:
            # Fallback - shouldn't happen but ensures role is always set
            self.role = "assistant"

    @property
    def token_count(self):
        return utils.misc.count_tokens(self.message.to_openai())

    def to_openai(self) -> dict:
        return {
            "role": self.role,
            "content": self.message.to_openai(),
        }

    def to_example(self) -> str:
        data = self.to_openai()
        return f"{data['role']}: {data['content']}"


@dataclass
class MessageHistory:
    system_prompt: str
    api_type: type[APIType.BaseAPI] = APIType.BaseAPI
    max_context: int = -1
    model: str | None = None  # TODO: this is very bad design, but it works
    messages: list[MessageContainer] = field(default_factory=list)
    message_cache: list[dict] = field(default_factory=list)

    def __post_init__(self):
        """Initialize with system message after dataclass init."""
        if not self.message_cache:  # Only add if not already present
            self.add_message(SystemMessage(comment=self.system_prompt), role="system")

    def get_token_count(self) -> int:
        """Get total token count for the message cache using API-specific counting."""
        return sum(
            self.api_type.count_tokens(message["content"], self.model)
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

    def add_message(
        self,
        message: BaseMessage,
        role: Literal["system", "user", "assistant"] | None = None,
    ):
        """Add a message and automatically prune if over context limit."""
        message_container = MessageContainer(message, role=role)
        self.messages.append(message_container)
        self.message_cache.append(message_container.to_openai())
        self.prune_message_cache()

    def to_openai(self):
        return self.message_cache

    def to_example(self):
        return "\n".join(message.to_example() for message in self.messages)
