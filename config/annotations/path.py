from __future__ import annotations

import pathlib
from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer

Path = Annotated[
    pathlib.Path,
    BeforeValidator(lambda value: pathlib.Path(value)),
    PlainSerializer(str, return_type=str, when_used="json"),
]

AbsolutePath = Annotated[
    pathlib.Path,
    BeforeValidator(lambda value: pathlib.Path(value).expanduser().resolve()),
    PlainSerializer(str, return_type=str, when_used="json"),
]


def _resolve_pattern(value) -> pathlib.Path:
    path = pathlib.Path(value)
    # Don't expand bare names, unlike AbsolutePath
    if str(path) == path.name:
        return path
    return path.expanduser().resolve()


PathPattern = Annotated[
    pathlib.Path,
    BeforeValidator(_resolve_pattern),
]
