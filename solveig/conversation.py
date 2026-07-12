"""Conversation - the running message history + cumulative usage passed to
every `agent.run()` call.

`Agent.run(usage=...)` accumulates request/token counts into the given
`RunUsage` in place across calls ("useful for resuming a conversation" per
its own docstring) - so there's no manual `+=` bookkeeping here, unlike the
old `MessageHistory`.
"""

from dataclasses import dataclass, field

from pydantic_ai.agent import AgentRunResult
from pydantic_ai.messages import ModelMessage
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
