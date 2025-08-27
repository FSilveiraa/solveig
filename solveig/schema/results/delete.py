from __future__ import annotations

from pathlib import Path

from .base import RequirementResult


class DeleteResult(RequirementResult):
    path: str | Path
