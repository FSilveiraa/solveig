from pydantic import BaseModel, Field
import json
from typing import List, Optional, Literal
from datetime import datetime, UTC

from schemas import FileReadRequirement, FileMetadataRequirement, CommandRequirement



class Message(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    role: Literal["user", "assistant"]

    def to_openai_message(self) -> dict:
        # Dump all fields (including defaults)
        data = self.model_dump()
        # Separate role from everything else
        role = data.pop("role")
        inner_content = data  # everything except role
        return {
            "role": role,
            "content": json.dumps(inner_content, ensure_ascii=False)
        }


# The LLM's response can be:
# - either a list of Requirements asking for more info
# - or a response with the final answer
class LLMMessage(Message):
    role: Literal["assistant"] = "assistant"
    comment: Optional[str] = None
    requirements: Optional[List[FileReadRequirement|FileMetadataRequirement|CommandRequirement]] = None

    # def get_content(self) -> str:
    #     formatted_requirements = [
    #         requirement.get_content() for requirement in self.requirements
    #     ]
    #     for requirement in self.requirements:
    #
    #     return self.comment


# The user's message will contain
# - either the inital prompt or optionally more prompting
# - optionally the responses to results asked by the LLM
class UserMessage(Message):
    role: Literal["user"] = "user"
    comment: Optional[str] = None
    results: Optional[List[RequirementResult]] = None


# I'm defining a class with the artificial type that's just a list of another type
class MessageHistory(BaseModel):
    messages: List[Message] = Field(default_factory=list)
    system_prompt: str

    def to_openai_format(self, system_prompt):
        messages = [ { "role": "system", "content": system_prompt } ]
        # TODO: have to do reverse adding, from the end and checking the token size at each one
        messages.extend(message for message in self)
