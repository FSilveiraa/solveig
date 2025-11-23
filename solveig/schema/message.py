import json
import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Union, cast

from pydantic import BaseModel, Field, TypeAdapter, create_model, field_validator

from solveig import SolveigConfig, utils
from solveig.llm import APIType
from solveig.schema import REQUIREMENTS
from solveig.schema.base import BaseSolveigModel
from solveig.schema.requirements import Requirement
from solveig.schema.results import RequirementResult

if TYPE_CHECKING:
    from solveig.interface import SolveigInterface


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
        return f"{self.role}: {self.to_openai()['content']}"


class SystemMessage(BaseMessage):
    role: Literal["system"] = "system"
    system_prompt: str

    def to_openai(self) -> dict:
        return {
            "role": self.role,
            "content": self.system_prompt,
        }


class UserComment(BaseModel):
    """A user's comment in the event stream."""
    comment: str


class UserMessage(BaseMessage):
    role: Literal["user"] = "user"
    responses: list[Union[RequirementResult, UserComment]]


class Task(BaseModel):
    """Individual task item with minimal fields for LLM JSON generation."""
    description: str = Field(
        ..., description="Clear description of what needs to be done"
    )
    status: Literal["pending", "in_progress", "completed", "failed"] = Field(
        default="pending", description="Current status of this task"
    )


class AssistantMessage(BaseMessage):
    """Assistant message containing a comment and optionally a task plan and a list of required operations"""
    role: Literal["assistant"] = "assistant"
    comment: str = Field(..., description="Conversation with user and plan description")
    tasks: list[Task] | None = Field(
        None, description="List of tasks to track and display"
    )
    requirements: list[Requirement] | None = (
        None  # Simplified - actual schema generated dynamically
    )

    async def display(self, interface: "SolveigInterface") -> None:
        """Display the assistant's message, including comment and tasks."""
        if self.comment:
            await interface.display_text(self.comment)

        if self.tasks:
            task_lines = []
            for i, task in enumerate(self.tasks, 1):
                status_emoji = {
                    "pending": "⚪",
                    "in_progress": "🔵",
                    "completed": "🟢",
                    "failed": "🔴",
                }[task.status]
                task_lines.append(
                    f"{'→' if task.status == 'in_progress' else ' '}  {status_emoji} {i}. {task.description}"
                )

            for line in task_lines:
                await interface.display_text(line)


# Cache for requirements union to avoid regenerating on every call
_last_requirements_config_hash = None
_last_requirements_union = None


def get_response_model(
    config: SolveigConfig | None = None,
    # returns a union of Requirement subclasses
) -> type[Requirement]:
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
        all_active_requirements: list[type[Requirement]] = list(
            REQUIREMENTS.registered.values()
        )
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
        raise ValueError("No response model available for LLM to use")

    # Create a Union of all requirement types for dynamic type checking
    requirements_union = cast(
        type[Requirement], Union[*all_active_requirements]
    )  # noqa: UP007

    # Cache the result
    _last_requirements_config_hash = config_hash
    _last_requirements_union = requirements_union

    return requirements_union


def get_assistant_response_model(
    config: SolveigConfig | None = None,
) -> type[BaseModel]:
    """
    Dynamically create an AssistantMessage model with a specific Union of requirements.
    This is done by creating a new model that inherits from the base AssistantMessage
    and only overrides the 'requirements' field with the correct dynamic type.
    """
    # Get the dynamic union of all concrete Requirement subclasses
    requirements_union = get_response_model(config)

    # Dynamically create the model, inheriting from AssistantMessage and overriding
    # only the 'requirements' field.
    dynamic_model = create_model(
        "DynamicAssistantMessage",
        requirements=(list[requirements_union] | None, Field(None)),
        __base__=AssistantMessage,
    )
    return dynamic_model


def get_response_model_json(config):
    response_model = get_assistant_response_model(config)
    schema = response_model.model_json_schema()
    return json.dumps(schema, indent=2, default=utils.misc.default_json_serialize)


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
    _event_queue: asyncio.Queue = field(default_factory=asyncio.Queue, init=False, repr=False)

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
