from __future__ import annotations

from pathlib import Path

from .base import RequirementResult


class CopyResult(RequirementResult):
    source_path: str | Path
    destination_path: str | Path
