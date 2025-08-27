from __future__ import annotations

from pathlib import Path

from .base import RequirementResult


class WriteResult(RequirementResult):
    path: str | Path
