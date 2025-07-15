from pydantic import BaseModel, TypeAdapter, Field, RootModel
import json
from pathlib import Path
from typing import List, Optional, Literal, Union, ClassVar, Any
from datetime import datetime, UTC



# Base class for things the LLM can request
class Requirement(BaseModel):
    type: str
    comment: str

    def is_possible(self, config) -> bool:
        raise NotImplementedError()


class FileRequirement(Requirement):
    path: str

    def is_possible(self, config) -> bool:
        possible = False
        negator = False
        for path in config.allowed_paths:
            # TODO: make the `path` variable itself be a Path instead of str
            if Path(self.path).is_relative_to(path):
                if self.mode_allowed(path.mode):
                    possible = True
                elif path.mode == "n":
                    negator = True
        return possible and not negator

    @staticmethod
    def mode_allowed(mode: str) -> bool:
        raise NotImplementedError()


class FileReadRequirement(FileRequirement):
    type: Literal["read"] = "read"

    @staticmethod
    def mode_allowed(mode: str) -> bool:
        return mode in {"r", "w"}


class FileMetadataRequirement(FileRequirement):
    type: Literal["metadata"] = "metadata"

    @staticmethod
    def mode_allowed(mode: str) -> bool:
        return mode in {"m", "r", "w"}


class CommandRequirement(Requirement):
    type: Literal["command"] = "command"
    command: str


# Base class for data returned for requirements
class RequirementResult(BaseModel):
    requirement: Union[FileReadRequirement|FileMetadataRequirement|CommandRequirement]

    def to_openai(self):
        return self.model_dump()


class FileReadResult(RequirementResult):
    content: str

    def to_openai(self):
        data = super().to_openai()
        requirement = data.pop("requirement")
        data["path"] = requirement["path"]
        return data


class FileMetadataResult(RequirementResult):
    content: str


class CommandResult(RequirementResult):
    stdout: str
    stderr: str

    def to_openai(self):
        data = super().to_openai()
        requirement = data.pop("requirement")
        data["command"] = requirement["command"]
        return data


# ==== Messages ====

class BaseMessage(BaseModel):
    def to_openai(self) -> dict:
        return self.model_dump()

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
    comment: str = None
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

    def to_example(self) -> dict:
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
            history.append({"role": "system", "content": self.system_prompt})
        # TODO: have to do reverse adding, from the end and checking the token size at each one
        history.extend(message.to_openai() for message in self.messages)
        return history

    def to_example(self):
        return "\n".join(message.to_example() for message in self.messages)
