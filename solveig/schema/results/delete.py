from __future__ import annotations

from .base import RequirementResult


class DeleteResult(RequirementResult):
    path: str
