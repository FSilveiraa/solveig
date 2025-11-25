import json
from typing import Literal

from pydantic import Field

from solveig import utils
from solveig.schema.base import BaseSolveigModel


class BaseMessage(BaseSolveigModel):
    role: Literal["system", "user", "assistant"]
    token_count: int = Field(default=-1, exclude=True)

    def to_openai(self) -> dict:
        data = self.model_dump()
        data.pop("role")
        # data.pop("token_count")
        return {
            "role": self.role,
            "content": json.dumps(data, default=utils.misc.default_json_serialize),
        }

    def __str__(self) -> str:
        return f"{self.role}: {self.to_openai()['content']}"
