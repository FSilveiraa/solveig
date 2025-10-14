from __future__ import annotations

from typing import Literal

from .base import RequirementResult


class DeleteResult(RequirementResult):
    title: Literal["delete"] = "delete"
    path: str
