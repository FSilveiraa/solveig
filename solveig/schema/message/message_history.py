import json
from dataclasses import dataclass, field

from pydantic import TypeAdapter

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.dynamic import get_result_classes, get_tools_union
from solveig.schema.message.assistant import AssistantMessage
from solveig.schema.message.pending import PendingMessageQueue
from solveig.schema.message.system import SystemMessage
from solveig.schema.message.user import UserComment, UserMessage
from solveig.schema.result import ToolResult

Message = SystemMessage | UserMessage | AssistantMessage


@dataclass
class MessageHistory:
    system_prompt: str
    config: SolveigConfig = field(default_factory=SolveigConfig)
    messages: list[Message] = field(default_factory=list)
    message_cache: list[tuple[dict, int]] = field(default_factory=list)
    token_count: int = field(default=0)  # Current cache size for pruning
    total_tokens_sent: int = field(default=0)  # Total sent to LLM across all calls
    total_tokens_received: int = field(default=0)  # Total received from LLM
    # contains both results to tools and user comments
    pending_messages: PendingMessageQueue = field(default_factory=PendingMessageQueue)

    def __post_init__(self):
        """Initialize with system message after dataclass init."""
        if not self.message_cache:  # Only add if not already present
            self.add_messages(SystemMessage(system_prompt=self.system_prompt))

    def __iter__(self):
        """Allow iteration over messages: for message in message_history."""
        return iter(self.messages)

    def prune_message_cache(self):
        """Remove old messages to stay under context limit, preserving system message."""
        if self.config.max_context <= 0:
            return

        while (
            self.token_count > self.config.max_context and len(self.message_cache) > 1
        ):
            message, size = self.message_cache.pop(1)
            self.token_count -= size

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
                # Correct the preceding user message's cached size using exact prompt_tokens.
                # Deducting the approximate user size gives the pre-user total; the difference
                # from prompt_tokens is the exact user message size. Works through pruning
                # because both sides have the same evictions already applied.
                if self.message_cache and isinstance(previous_user_message := self.messages[-1], UserMessage):
                    approx_user_size = previous_user_message.token_count
                    exact_user_size = sent - (self.token_count - approx_user_size)
                    if exact_user_size > 0:
                        previous_user_message.token_count = exact_user_size
                        dumped_message, _ = self.message_cache[-1]
                        self.message_cache[-1] = (dumped_message, exact_user_size)

                        # If there are multiple user messages in a row (cancel sending and add another)
                        # then we can't just correct the latest one and leave the others with encoder counts
                        # Iterate the previous user messages, if any, and set their sizes to 0
                        for i in reversed(range(-1 * len(self.messages), -1)):
                            previous_message = self.messages[i]
                            if not isinstance(previous_message, UserMessage):
                                break
                            previous_message.token_count = 0
                            dumped_message, _ = self.message_cache[i]
                            self.message_cache[i] = (dumped_message, 0)

                self.token_count = sent + received
                self.total_tokens_sent += sent
                self.total_tokens_received += received
            else:
                # Update token count using encoder approximation for all other messages
                message_size = self.config.api_type.count_tokens(
                    message_serialized["content"],
                    model=self.config.model,
                    encoder=self.config.encoder,
                )
                self.token_count += message_size

            # Regardless of how we found the token count, update it for that message
            message.token_count = message_size
            self.messages.append(message)
            self.message_cache.append((message_serialized, message.token_count))

        self.prune_message_cache()

    async def add_result(self, result: ToolResult):
        """Producer method to add a tool result to the event queue."""
        await self.pending_messages.put(result)

    async def add_user_comment(self, comment: UserComment | str):
        """Producer method to add a user comment to the event queue."""
        if isinstance(comment, str):
            comment = UserComment(comment=comment)
        await self.pending_messages.put(comment)

    async def condense_responses_into_user_message(
        self, interface: SolveigInterface, wait_for_input: bool = True
    ) -> UserMessage | None:
        """
        Consolidates events into a UserMessage, optionally waiting for user input.

        This method consumes events from the queue. If `wait_for_input` is True
        and no UserComment is found among the currently queued events, it will
        block and wait for the user to provide one before creating the message.
        """
        responses = []
        has_user_comment = False

        # 1. Consume all events that are *already* in the queue.
        while not self.pending_messages.empty():
            event = self.pending_messages.get_nowait()
            if isinstance(event, UserComment):
                has_user_comment = True
            responses.append(event)

        # 2. If we must wait for input and haven't seen a user comment, block and wait.
        if wait_for_input and not has_user_comment:
            # Block until the user provides the next comment.
            async with interface.with_animation("Awaiting input..."):
                event = await self.pending_messages.get()
            responses.append(event)

        # 3. If we have collected any events, create and display the message.
        if responses:
            user_message = UserMessage(responses=responses)
            self.add_messages(user_message)
            await user_message.display(interface)
            return user_message
        return None

    def load_from_session(self, session_data: dict) -> None:
        """Reconstruct messages from a stored session dict and load them into history."""
        tool_adapter: TypeAdapter = TypeAdapter(get_tools_union(self.config))
        result_classes = get_result_classes(self.config)
        messages: list[Message] = []
        pending_tools: list = []

        for msg in session_data.get("messages", []):
            role = msg.get("role", "unknown")
            content = msg.get("content") or ""
            try:
                parsed = json.loads(content)
            except (json.JSONDecodeError, AttributeError):
                parsed = {}

            if role == "assistant":
                pending_tools = []
                for tool_dict in parsed.get("tools") or []:
                    try:
                        pending_tools.append(tool_adapter.validate_python(tool_dict))
                    except Exception:
                        pass
                messages.append(
                    AssistantMessage(
                        comment=parsed.get("comment", content),
                        tasks=parsed.get("tasks"),
                        tools=pending_tools or None,
                    )
                )

            elif role == "user":
                responses: list[ToolResult | UserComment] = []
                result_idx = 0
                for r in parsed.get("responses", []):
                    if "title" in r and "accepted" in r:
                        tool = (
                            pending_tools[result_idx]
                            if result_idx < len(pending_tools)
                            else None
                        )
                        result_idx += 1
                        if tool is not None:
                            result_cls = result_classes.get(
                                r.get("title", ""), ToolResult
                            )
                            responses.append(
                                result_cls.model_validate({**r, "tool": tool})
                            )
                    elif "comment" in r:
                        responses.append(UserComment(comment=r["comment"]))
                if responses:
                    messages.append(UserMessage(responses=responses))  # type: ignore[arg-type]

        self.load_messages(messages)

    def load_messages(self, messages: list[Message]) -> None:
        """Replace message history in-place from reconstructed Message objects.

        The system message at index 0 is preserved (current config's prompt).
        Both the Pydantic messages list and the OpenAI cache are fully populated.
        """
        sys_msg = self.messages[0]
        sys_entry = self.message_cache[0]
        self.messages = [sys_msg]
        self.message_cache = [sys_entry]
        self.token_count = sys_entry[1]
        self.total_tokens_sent = 0
        self.total_tokens_received = 0
        self.add_messages(*messages)

    def update_system_prompt(self, new_prompt: str) -> None:
        """Replace the system message in-place and adjust the token count."""
        self.system_prompt = new_prompt
        new_sys_msg = SystemMessage(system_prompt=new_prompt)
        serialized = new_sys_msg.to_openai()
        new_size = self.config.api_type.count_tokens(
            serialized["content"],
            model=self.config.model,
            encoder=self.config.encoder,
        )
        old_size = self.message_cache[0][1]
        self.token_count = self.token_count - old_size + new_size
        self.message_cache[0] = (serialized, new_size)

    def to_openai(self):
        """Return cache for OpenAI API."""
        return [message for message, _ in self.message_cache]

    def to_example(self):
        return "\n".join(
            str(message) for message in self.messages if message.role != "system"
        )
