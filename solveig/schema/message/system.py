from typing import Literal

from solveig.schema.message.base import BaseMessage


class SystemMessage(BaseMessage):
    role: Literal["system"] = "system"
    system_prompt: str

    def to_openai(self) -> dict:
        return {
            "role": self.role,
            "content": self.system_prompt,
        }
