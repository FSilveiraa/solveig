import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from .. import utils
from .requirement import (
    CommandRequirement,
    CopyRequirement,
    DeleteRequirement,
    MoveRequirement,
    ReadRequirement,
    WriteRequirement,
)
from .result import (
    CommandResult,
    CopyResult,
    DeleteResult,
    MoveResult,
    ReadResult,
    WriteResult,
)


class BaseMessage(BaseModel):
    comment: str | None

    def to_openai(self) -> dict:
        return self.model_dump()

    @field_validator("comment", mode="before")
    @classmethod
    def strip_name(cls, comment):
        return comment.strip()


# The user's message will contain
# - either the inital prompt or optionally more prompting
# - optionally the responses to results asked by the LLM
class UserMessage(BaseMessage):
    comment: str | None = None
    results: (
        list[
            ReadResult
            | WriteResult
            | CommandResult
            | MoveResult
            | CopyResult
            | DeleteResult
        ]
        | None
    ) = None

    def to_openai(self) -> dict:
        data = super().to_openai()
        data["results"] = (
            [result.to_openai() for result in self.results]
            if self.results is not None
            else None
        )
        return data


# The LLM's response can be:
# - either a list of Requirements asking for more info
# - or a response with the final answer
class LLMMessage(BaseMessage):
    requirements: (
        list[
            ReadRequirement
            | WriteRequirement
            | CommandRequirement
            | MoveRequirement
            | CopyRequirement
            | DeleteRequirement
        ]
        | None
    ) = None


@dataclass
class MessageContainer:
    message: UserMessage | LLMMessage
    content: str = field(init=False)
    token_count: int = field(init=False)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    role: Literal["user", "assistant"] = field(init=False)

    def __init__(self, message: LLMMessage | UserMessage):
        self.message = message
        self.role = "user" if isinstance(message, UserMessage) else "assistant"
        self.content = json.dumps(message.to_openai())
        self.token_count = utils.misc.count_tokens(self.content)

    def to_openai(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
        }

    def to_example(self) -> str:
        data = self.to_openai()
        return f"{data['role']}: {data['content']}"


@dataclass
class MessageHistory:
    system_prompt: str | None = None
    max_context: int = -1
    messages: list[MessageContainer] = field(default_factory=list)
    message_cache: list[dict] = field(default_factory=list)

    def get_token_count(self):
        count = utils.misc.count_tokens(self.system_prompt) if self.system_prompt else 0
        return count + sum(message["content"] for message in self.message_cache)

    def prune_message_cache(self):
        if self.max_context >= 0:
            while self.get_token_count() > self.max_context:
                self.message_cache.pop(0)

    def add_message(self, message: UserMessage | LLMMessage):
        message_container = MessageContainer(message)
        self.messages.append(message_container)
        self.message_cache.append(message_container.to_openai())
        self.prune_message_cache()

    def to_openai(self):
        history = []
        if self.system_prompt:
            history.append({"role": "system", "content": self.system_prompt})
        history.extend(message.to_openai() for message in self.messages)
        return history + self.message_cache

    def to_example(self):
        return "\n".join(message.to_example() for message in self.messages)
