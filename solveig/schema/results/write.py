from __future__ import annotations

from typing import Literal

from .base import RequirementResult


class WriteResult(RequirementResult):
    title: Literal["write"] = "write"
    path: str
