import asyncio
from dataclasses import dataclass, field

from openai.types import CompletionUsage

from solveig import APIType
from solveig.interface import SolveigInterface
from solveig.schema.message.assistant import AssistantMessage
from solveig.schema.message.system import SystemMessage
from solveig.schema.message.user import UserComment, UserMessage
from solveig.schema.result import ToolResult

Message = SystemMessage | UserMessage | AssistantMessage


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
    # contains both results to tools and user comments
    current_responses: asyncio.Queue[UserComment | ToolResult] = field(
        default_factory=asyncio.Queue, init=False, repr=False
    )

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

            # The _raw_response is only present on AssistantMessage, and only when it's from a real API call
            if isinstance(message, AssistantMessage) and hasattr(
                message, "_raw_response"
            ):
                # Update token count using API usage field from the raw response
                raw_response = message._raw_response
                sent = raw_response.usage.prompt_tokens
                message_size = received = raw_response.usage.completion_tokens
                self.token_count = sent + received
                self.total_tokens_sent += sent
                self.total_tokens_received += received
            else:
                # Update token count using encoder approximation for all other messages
                message_size = self.api_type.count_tokens(
                    message_serialized["content"], self.encoder
                )
                self.token_count += message_size

            # Regardless of how we found the token count, update it for that message
            message.token_count = message_size
            self.messages.append(message)
            self.message_cache.append((message_serialized, message.token_count))

        self.prune_message_cache()

    async def add_result(self, result: ToolResult):
        """Producer method to add a tool result to the event queue."""
        await self.current_responses.put(result)

    async def add_user_comment(self, comment: UserComment | str):
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
        return [message for message, _ in self.message_cache]

    def to_example(self):
        return "\n".join(
            str(message) for message in self.messages if message.role != "system"
        )
