from __future__ import annotations

from .base import RequirementResult


class WriteResult(RequirementResult):
    path: str
