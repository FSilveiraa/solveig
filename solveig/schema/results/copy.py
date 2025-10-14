from __future__ import annotations

from .base import RequirementResult


class CopyResult(RequirementResult):
    source_path: str
    destination_path: str
