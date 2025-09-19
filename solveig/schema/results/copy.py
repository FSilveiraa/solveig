from __future__ import annotations

from pathlib import PurePath

from .base import RequirementResult


class CopyResult(RequirementResult):
    source_path: str | PurePath
    destination_path: str | PurePath
