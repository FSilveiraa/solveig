"""
Schema definitions for Solveig's structured communication with LLMs.

This module defines the data structures used for:
- Messages exchanged between user, LLM, and system
- Requirements (file operations, shell commands)
- Results and error handling
"""

from dataclasses import fields, is_dataclass
from os import PathLike

import anyio
from pydantic import BaseModel, field_serializer


class BaseSolveigModel(BaseModel):
    pass

    # model_config = ConfigDict(arbitrary_types_allowed=True)

    @classmethod
    def _dump_pydantic_field(cls, obj):
        if is_dataclass(obj):
            result = {}
            for f in fields(obj):
                val = getattr(obj, f.name)
                result[f.name] = cls._dump_pydantic_field(val)
            return result
        # NOTE: Not really a hack, but if you don't do this and call model_dump()
        # on a sub-class of an abstract BaseModel, it will only dump the fields on
        # the abstract. If you call BaseMessage.model_dump() on a child object,
        # it won't include fields from the child
        elif isinstance(obj, BaseModel):
            return obj.model_dump()
        elif isinstance(obj, PathLike) or isinstance(obj, anyio.Path):
            return str(obj)
        elif isinstance(obj, list):
            return [cls._dump_pydantic_field(v) for v in obj]
        elif isinstance(obj, dict):
            return {
                cls._dump_pydantic_field(k): cls._dump_pydantic_field(v)
                for k, v in obj.items()
            }
        else:
            return obj

    @field_serializer("*")
    def serialize_all_fields(self, obj, _info):
        return self._dump_pydantic_field(obj)
