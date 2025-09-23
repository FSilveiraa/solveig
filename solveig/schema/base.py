"""
Schema definitions for Solveig's structured communication with LLMs.

This module defines the data structures used for:
- Messages exchanged between user, LLM, and system
- Requirements (file operations, shell commands)
- Results and error handling
"""

from dataclasses import fields, is_dataclass
from pathlib import PurePath

from pydantic import BaseModel, field_serializer


class BaseSolveigModel(BaseModel):
    @classmethod
    def _dump_pydantic_field(cls, obj):
        if is_dataclass(obj):
            result = {}
            for f in fields(obj):
                val = getattr(obj, f.name)
                result[f.name] = cls._dump_pydantic_field(val)
            return result
        elif isinstance(obj, BaseModel):
            return obj.model_dump()
        elif isinstance(obj, PurePath):
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
