import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Annotated, Union

from pydantic import BaseModel, field_validator, Field

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
        # Magic semantics explained
        # Means that, if 2 requirements have the same JSON structure like
        # copy and move (comment, title, source, destination), the `title`
        # field is used to disambiguate them
        list[
            Annotated[
                Union[
                    ReadRequirement
                    | WriteRequirement
                    | CommandRequirement
                    | MoveRequirement
                    | CopyRequirement
                    | DeleteRequirement
                ],
                Field(discriminator="title")
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

    def __init__(self, message: BaseMessage, role: str | None = None):
        self.message = message
        if role:
            self.role = role
        elif isinstance(message, UserMessage):
            self.role = "user"
        elif isinstance(message, LLMMessage):
            self.role = "assistant"
        else:
            self.role = "system"
        self.content = json.dumps(message.to_openai())
        self.token_count = utils.misc.count_tokens(self.content)

    def to_openai(self) -> dict:
        return {
            "role": self.role,
            "content": json.dumps(self.message.to_openai()),
        }

    def to_example(self) -> str:
        data = self.to_openai()
        return f"{data['role']}: {data['content']}"


# @dataclass
class MessageHistory:
    # system_prompt: dict = None
    max_context: int = -1
    messages: list[MessageContainer] # = field(default_factory=list)
    message_cache: list[dict] # = field(default_factory=list)

    def __init__(self, system_prompt, max_context: int = -1, messages: list[MessageContainer] = None, message_cache: list[dict] = None):
        self.messages = messages or []
        self.message_cache = message_cache or []
        self.add_message(BaseMessage(comment=system_prompt), role="system")

    # def __post_init__(self):
    #     if isinstance(self.system_prompt, str):
    #         self.system_prompt = {
    #             "role": "system",
    #             "content": self.system_prompt.strip()
    #         }

    def get_token_count(self):
        # count = 0
        # if self.system_prompt:
        #     if isinstance(self.system_prompt, dict):
        #         count = len(self.system_prompt["content"])
        #     else:
        #         count = len(self.system_prompt)
        return sum(utils.misc.count_tokens(message["content"]) for message in self.message_cache)

    def prune_message_cache(self):
        if self.max_context >= 0:
            while self.get_token_count() > self.max_context:
                self.message_cache.pop(0)

    def add_message(self, message: BaseMessage, role: str | None = None):
        message_container = MessageContainer(message, role=role)
        self.messages.append(message_container)
        self.message_cache.append(message_container.to_openai())
        self.prune_message_cache()

    def to_openai(self):
        return self.message_cache

    def to_example(self):
        return "\n".join(message.to_example() for message in self.messages)
