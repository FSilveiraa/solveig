from __future__ import annotations

from pathlib import PurePath

from .base import RequirementResult


class WriteResult(RequirementResult):
    path: str | PurePath
