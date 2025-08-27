import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from .. import utils
from .requirements import (
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

    def to_openai(self) -> str:
        return json.dumps(self.model_dump())

    @field_validator("comment", mode="before")
    @classmethod
    def strip_name(cls, comment):
        return comment.strip()


class SystemMessage(BaseMessage):
    def to_openai(self):
        return self.comment


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
class LLMMessage(BaseMessage):
    requirements: (
        # Magic semantics explained
        # Means that, if 2 requirements have the same JSON structure like
        # copy and move (comment, title, source, destination), the `title`
        # field is used to disambiguate them
        list[
            Annotated[
                ReadRequirement
                | WriteRequirement
                | CommandRequirement
                | MoveRequirement
                | CopyRequirement
                | DeleteRequirement,
                Field(discriminator="title"),
            ]
        ]
        | None
    ) = None


@dataclass
class MessageContainer:
    message: BaseMessage
    content: str = field(init=False)
    token_count: int = field(init=False)
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
        elif isinstance(message, LLMMessage):
            self.role = "assistant"
        elif isinstance(message, SystemMessage):
            self.role = "system"
        self.content = message.to_openai()
        self.token_count = utils.misc.count_tokens(self.content)

    def to_openai(self) -> dict:
        return {
            "role": self.role,
            "content": self.message.to_openai(),
        }

    def to_example(self) -> str:
        data = self.to_openai()
        return f"{data['role']}: {data['content']}"


# @dataclass
class MessageHistory:
    max_context: int = -1
    messages: list[MessageContainer]
    message_cache: list[dict]

    def __init__(
        self,
        system_prompt,
        messages: list[MessageContainer] | None = None,
        message_cache: list[dict] | None = None,
    ):
        self.messages = messages or []
        self.message_cache = message_cache or []
        self.add_message(SystemMessage(comment=system_prompt), role="system")

    def get_token_count(self):
        return sum(
            utils.misc.count_tokens(message["content"])
            for message in self.message_cache
        )

    def prune_message_cache(self):
        if self.max_context >= 0:
            while self.get_token_count() > self.max_context:
                self.message_cache.pop(0)

    def add_message(
        self,
        message: BaseMessage,
        role: Literal["system", "user", "assistant"] | None = None,
    ):
        message_container = MessageContainer(message, role=role)
        self.messages.append(message_container)
        self.message_cache.append(message_container.to_openai())
        self.prune_message_cache()

    def to_openai(self):
        return self.message_cache

    def to_example(self):
        return "\n".join(message.to_example() for message in self.messages)
