from pydantic import BaseModel, Field
import json
from typing import List, Optional, Literal, Union
from datetime import datetime, UTC

from schema.requirement import *



class BaseMessage(BaseModel):
    comment: str

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
    comment: Optional[str] = None
    results: Optional[List[FileReadResult|FileMetadataResult|CommandResult]] = None

    def to_openai(self) -> dict:
        data = super().to_openai()
        data["results"] = [
            result.to_openai() for result in self.results
        ] if self.results is not None else None
        return data


# The LLM's response can be:
# - either a list of Requirements asking for more info
# - or a response with the final answer
class LLMMessage(BaseMessage):
    requirements: Optional[List[FileReadRequirement|FileMetadataRequirement|CommandRequirement]] = None


class MessageContainer(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    role: Literal["user", "assistant"]
    message: Union[UserMessage, LLMMessage]

    def to_openai(self) -> dict:
        # Dump all fields (including defaults)
        # Separate role from everything else
        # role = data.pop("role")
        # inner_content = data  # everything except role
        return {
            "role": self.role,
            "content": json.dumps(self.message.to_openai())
        }

    def to_example(self) -> str:
        data = self.to_openai()
        return f"{data['role']}: {data['content']}"


class MessageHistory(BaseModel):
    messages: List[MessageContainer] = Field(default_factory=list)
    system_prompt: str

    def add_message(self, message: UserMessage|LLMMessage):
        self.messages.append(MessageContainer(role=("user" if isinstance(message, UserMessage) else "assistant"), message=message))

    def to_openai(self):
        history = []
        if self.system_prompt:
            history.append({ "role": "system", "content": self.system_prompt })
        # TODO: have to do reverse adding, from the end and checking the token size at each one
        history.extend(message.to_openai() for message in self.messages)
        return history

    def to_example(self):
        return "\n".join(message.to_example() for message in self.messages)
