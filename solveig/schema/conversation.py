"""Conversation - thin wrapper around pydantic-ai's own message list + usage.

Replaces the old `MessageHistory` (built around a bespoke `Message` union and
manual OpenAI-dict caching). pydantic-ai already tracks a conversation as
`list[ModelMessage]` and cumulative token usage as `RunUsage` - this class
just carries those between successive `agent.run()` calls.
"""

from dataclasses import dataclass, field

from pydantic_ai.agent import AgentRunResult
from pydantic_ai.messages import ModelMessage


@dataclass
class Conversation:
    messages: list[ModelMessage] = field(default_factory=list)
    total_tokens_sent: int = 0
    total_tokens_received: int = 0

    def apply(self, result: AgentRunResult) -> None:
        """Absorb a completed run's messages and usage into the conversation."""
        self.messages = result.all_messages()
        usage = result.usage
        self.total_tokens_sent += usage.input_tokens
        self.total_tokens_received += usage.output_tokens
