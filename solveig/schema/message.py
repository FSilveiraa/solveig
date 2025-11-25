import json
import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Union, cast

from openai.types import CompletionUsage
from pydantic import BaseModel, Field, create_model

from solveig import SolveigConfig, utils
from solveig.llm import APIType
from solveig.schema import REQUIREMENTS
from solveig.schema.base import BaseSolveigModel
from solveig.schema.requirements import Requirement
from solveig.schema.results import RequirementResult

if TYPE_CHECKING:
    from solveig.interface import SolveigInterface


class BaseMessage(BaseSolveigModel):
    role: Literal["system", "user", "assistant"]
    token_count: int = Field(default=-1, exclude=True)

    def to_openai(self) -> dict:
        data = self.model_dump()
        data.pop("role")
        # data.pop("token_count")
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

    async def display(self, interface: "SolveigInterface"):
        """Display the user's comments from the message."""
        comments = [
            response.comment
            for response in self.responses
            if isinstance(response, UserComment)
        ]
        if comments:
            await interface.display_section("User")
            for comment in comments:
                await interface.display_comment(f" {comment}")

    @property
    def comment(self) -> str:
        return "\n".join(response.comment for response in self.responses if isinstance(response, UserComment))


# Define statuses and their corresponding emojis
TASK_STATUS_MAP = {
    "pending": "⚪",
    "ongoing": "🔵",
    "completed": "🟢",
    "failed": "🔴",
}
# TaskStatus = Literal[tuple(TASK_STATUS_MAP.keys())]


class Task(BaseModel):
    """Individual task item with minimal fields for LLM JSON generation."""
    description: str = Field(
        ..., description="Clear description of what needs to be done"
    )
    status: Literal["pending", "ongoing", "completed", "failed"] = Field(
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
                status_emoji = TASK_STATUS_MAP[task.status]
                task_lines.append(
                    f"{'→' if task.status == 'ongoing' else ' '}  {status_emoji} {i}. {task.description}"
                )

            async with interface.with_group("Tasks"):
                for line in task_lines:
                    await interface.display_text(line)


# Cache for requirements union to avoid regenerating on every call
class CACHED_RESPONSE_MODEL:
    config_hash: str | None = None
    requirements_union: type[Requirement] | None = None
    message_class: type[AssistantMessage] | None = None


def _ensure_requirements_union_cached(config: SolveigConfig | None = None):
    """Internal helper to ensure requirements union is cached."""
    # Generate config hash for caching
    config_hash = None
    if config:
        config_hash = hash(config.to_json(indent=None, sort_keys=True))

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
        from solveig.schema.requirements.command import CommandRequirement
        all_active_requirements = [
            req for req in all_active_requirements if req != CommandRequirement
        ]

    # Handle empty registry case
    if not all_active_requirements:
        raise ValueError("No response model available for LLM to use")

    # Create a Union of all requirement types
    requirements_union = cast(
        type[Requirement], Union[*all_active_requirements]
    )

    # Cache the result and clear dependent cache
    CACHED_RESPONSE_MODEL.config_hash = config_hash
    CACHED_RESPONSE_MODEL.requirements_union = requirements_union
    CACHED_RESPONSE_MODEL.message_class = create_model(
        "DynamicAssistantMessage",
        requirements=(list[CACHED_RESPONSE_MODEL.requirements_union] | None, Field(None)),
        __base__=AssistantMessage,
    )


def get_requirements_union(config: SolveigConfig | None = None) -> type[Requirement]:
    """Get the requirements union type with caching."""
    _ensure_requirements_union_cached(config)
    return CACHED_RESPONSE_MODEL.requirements_union


def get_response_model(
    config: SolveigConfig | None = None,
) -> type[AssistantMessage]:
    """Get the AssistantMessage model with dynamic requirements field."""
    _ensure_requirements_union_cached(config)
    return CACHED_RESPONSE_MODEL.message_class


def get_response_model_json(config):
    response_model = get_response_model(config)
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
    message_cache: list[tuple[dict, int]] = field(default_factory=list)
    token_count: int = field(default=0)  # Current cache size for pruning
    total_tokens_sent: int = field(default=0)  # Total sent to LLM across all calls
    total_tokens_received: int = field(default=0)  # Total received from LLM
    # contains both results to requirements and user comments
    current_responses: asyncio.Queue[UserComment | RequirementResult] = field(default_factory=asyncio.Queue, init=False, repr=False)

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
            if len(self.message_cache) > 1:
                message, size = self.message_cache.pop(1)
                # self.token_count -= self.api_type.count_tokens(message, self.encoder)
                self.token_count -= size
            else:
                break

    def add_messages(
        self,
        *messages: Message,
    ):
        """Add a message and automatically prune if over context limit."""
        for message in messages:
            message_serialized = message.to_openai()

            try:
                raw_response = message._raw_response
                _ = raw_response.usage

            except AttributeError:
                # Update token count using encoder approximation, necessary for pruning
                message_size = self.api_type.count_tokens(
                    message_serialized["content"], self.encoder
                )
                self.token_count += message_size

            else:
                # Update token count using API usage field
                sent = raw_response.usage.prompt_tokens
                message_size = received = raw_response.usage.completion_tokens
                self.token_count = sent + received
                self.total_tokens_sent += sent
                self.total_tokens_received += received

            # Regardless of how we found the token count, update it for that message
            message.token_count = message_size
            self.messages.append(message)
            self.message_cache.append((message_serialized, message.token_count))

        self.prune_message_cache()

    async def add_result(self, result: RequirementResult):
        """Producer method to add a tool result to the event queue."""
        await self.current_responses.put(result)

    async def add_user_comment(self, comment: Union[UserComment, str]):
        """Producer method to add a user comment to the event queue."""
        if isinstance(comment, str):
            comment = UserComment(comment=comment)
        await self.current_responses.put(comment)

    def record_api_usage(self, usage: "CompletionUsage") -> None:
        """Updates the total token counts from the API's response."""
        if usage:
            self.total_tokens_sent += usage.prompt_tokens
            self.total_tokens_received += usage.completion_tokens

    async def condense_responses_into_user_message(
        self, interface: "SolveigInterface", wait_for_input: bool = True
    ):
        """
        Consolidates events into a UserMessage, optionally waiting for user input.

        This method consumes events from the queue. If `wait_for_input` is True
        and no UserComment is found among the currently queued events, it will
        block and wait for the user to provide one before creating the message.
        """
        responses = []
        has_user_comment = False

        # 1. Consume all events that are *already* in the queue.
        while not self.current_responses.empty():
            event = self.current_responses.get_nowait()
            if isinstance(event, UserComment):
                has_user_comment = True
            responses.append(event)

        # 2. If we must wait for input and haven't seen a user comment, block and wait.
        if wait_for_input and not has_user_comment:
            # Block until the user provides the next comment.
            async with interface.with_animation("Awaiting input..."):
                event = await self.current_responses.get()
            responses.append(event)

        # 3. If we have collected any events, create and display the message.
        if responses:
            user_message = UserMessage(responses=responses)
            self.add_messages(user_message)
            await user_message.display(interface)

    def to_openai(self):
        """Return cache for OpenAI API."""
        return [
            message for message, _ in self.message_cache
        ]

    def to_example(self):
        return "\n".join(
            str(message) for message in self.messages if message.role != "system"
        )
