import json
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Union

from pydantic import Field, field_validator

from .. import SolveigConfig, utils
from ..llm import APIType
from .base import BaseSolveigModel
from .requirements import Requirement
from .results import RequirementResult


class BaseMessage(BaseSolveigModel):
    token_count: int = Field(default_factory=lambda: 0, exclude=True)
    role: Literal["system", "user", "assistant"]

    def to_openai(self) -> dict:
        data = self.model_dump()
        data.pop("role")
        return {
            "role": self.role,
            "content": json.dumps(data, default=utils.misc.default_json_serialize),
        }

    def __str__(self) -> str:
        return f"{self.role}: {self.to_openai()["content"]}"


class SystemMessage(BaseMessage):
    role: Literal["system"] = "system"
    system_prompt: str

    def to_openai(self) -> dict:
        return {
            "role": self.role,
            "content": self.system_prompt,
        }


# The user's message will contain
# - either the initial prompt or optionally more prompting
# - optionally the responses to results asked by the LLM
class UserMessage(BaseMessage):
    role: Literal["user"] = "user"
    comment: str = ""
    results: list[RequirementResult] | None = None

    @field_validator("comment", mode="before")
    @classmethod
    def strip_comment(cls, comment):
        return (comment or "").strip()


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
    # HACK: we tell mypy to ignore typing here
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


# Cache for requirements union to avoid regenerating on every call
_last_requirements_config_hash = None
_last_requirements_union = None


def get_requirements_union_for_streaming(
    config: SolveigConfig | None = None,
) -> type[Requirement] | None:
    """Get the requirements union type for streaming individual requirements with caching."""
    global _last_requirements_config_hash, _last_requirements_union

    # Generate config hash for caching
    config_hash = None
    if config:
        config_hash = hash(config.to_json(indent=None, sort_keys=True))

    # Return cached union if config hasn't changed
    if (
        config_hash == _last_requirements_config_hash
        and _last_requirements_union is not None
    ):
        return _last_requirements_union

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
        _last_requirements_config_hash = config_hash
        _last_requirements_union = None
        return None

    # Create union using typing.Union for Instructor compatibility
    if len(all_active_requirements) == 1:
        requirements_union = all_active_requirements[0]
    else:
        from typing import cast

        # HACK: Cast to tell mypy this is a valid Union type
        requirements_union = cast(type[Requirement], Union[*all_active_requirements])

    # Cache the result
    _last_requirements_config_hash = config_hash
    _last_requirements_union = requirements_union

    return requirements_union


# Type alias for any message type
Message = SystemMessage | UserMessage | AssistantMessage
UserMessage.model_rebuild()
AssistantMessage.model_rebuild()


@dataclass
class MessageHistory:
    system_prompt: str
    api_type: type[APIType.BaseAPI] = APIType.BaseAPI
    max_context: int = -1
    encoder: str | None = None
    messages: list[Message] = field(default_factory=list)
    message_cache: list[dict] = field(default_factory=list)
    token_count: int = field(default=0)  # Current cache size for pruning
    total_tokens_sent: int = field(default=0)  # Total sent to LLM across all calls
    total_tokens_received: int = field(default=0)  # Total received from LLM

    def __post_init__(self):
        """Initialize with system message after dataclass init."""
        if not self.message_cache:  # Only add if not already present
            self.add_messages(SystemMessage(system_prompt=self.system_prompt))

    def __iter__(self):
        """Allow iteration over messages: for message in message_history."""
        return iter(self.messages)

    def prune_message_cache(self):
        """Remove old messages to stay under context limit, preserving system message."""
        if self.max_context <= 0:
            return

        while self.token_count > self.max_context and len(self.message_cache) > 1:
            # Always preserve the first message (system prompt) if possible
            if len(self.message_cache) > 1:
                # Remove the second message (oldest non-system message)
                message = self.message_cache.pop(1)
                self.token_count -= self.api_type.count_tokens(message, self.encoder)
            else:
                break  # Can't remove system message

    def add_messages(
        self,
        *messages: Message,
    ):
        """Add a message and automatically prune if over context limit."""
        for message in messages:
            message_dumped = message.to_openai()
            token_count = self.api_type.count_tokens(
                message_dumped["content"], self.encoder
            )

            # Update current cache size for pruning
            self.token_count += token_count

            # Track total received tokens for assistant messages
            if message.role == "assistant":
                self.total_tokens_received += token_count

            self.messages.append(message)
            self.message_cache.append(message_dumped)
        self.prune_message_cache()

    def to_openai(self, update_sent_count=False):
        """Return cache for OpenAI API. If update_sent_count=True, add current cache size to total_tokens_sent."""
        if update_sent_count:
            self.total_tokens_sent += self.token_count
        return self.message_cache

    def to_example(self):
        return "\n".join(
            str(message) for message in self.messages if message.role != "system"
        )
