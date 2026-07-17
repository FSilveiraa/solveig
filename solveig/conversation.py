"""Conversation - the running message history + cumulative usage passed to
every `agent.run()` call.

`Agent.run(usage=...)` accumulates request/token counts into the given
`RunUsage` in place across calls ("useful for resuming a conversation" per
its own docstring) - so there's no manual `+=` bookkeeping here, unlike the
old `MessageHistory`.
"""

from dataclasses import dataclass, field

from pydantic_ai.agent import AgentRunResult
from pydantic_ai.messages import ModelMessage, TextPart, ThinkingPart, UserPromptPart
from pydantic_ai.usage import RunUsage


@dataclass
class Conversation:
    messages: list[ModelMessage] = field(default_factory=list)
    usage: RunUsage = field(default_factory=RunUsage)

    def apply(self, result: AgentRunResult) -> None:
        """Absorb a completed run's messages. Usage is already accumulated
        in place, since the same `usage` instance is passed into every
        `agent.run()` call."""
        self.messages = result.all_messages()

    def edit_part(self, msg_index: int, part_index: int, new_text: str) -> None:
        """Overwrite the text content of a single part in place - a
        `UserPromptPart`, `TextPart`, or `ThinkingPart`. No truncation."""
        part = self.messages[msg_index].parts[part_index]
        if not isinstance(part, UserPromptPart | TextPart | ThinkingPart):
            raise ValueError(f"{type(part).__name__} is not an editable part type")
        part.content = new_text

    def delete_from(self, msg_index: int) -> None:
        """Drop `messages[msg_index]` and everything after it."""
        self.messages = self.messages[:msg_index]
