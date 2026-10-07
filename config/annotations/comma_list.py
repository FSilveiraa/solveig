from __future__ import annotations

from typing import TypeVar, Annotated

from pydantic import BeforeValidator, PlainSerializer
from pydantic_settings import NoDecode

T = TypeVar("T")
CommaSeparated = Annotated[
    list[T],
    # Don't try to decode early with a default validator
    NoDecode,
    # Converts "a, bb,c," -> ["a", "bb", "c"]
    BeforeValidator(
        lambda value: [
            token.strip() for token in value.split(",")
            if token.strip()
        ] if isinstance(value, str) else value
    ),
    # Serializes ["a", "bb", "c"] -> "a,bb,c"
    PlainSerializer(
        lambda seq: ",".join(str(token) for token in seq),
        when_used="json",
    ),
]
