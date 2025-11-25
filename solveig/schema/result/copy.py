from __future__ import annotations

from typing import Literal

from .base import RequirementResult


class CopyResult(RequirementResult):
    title: Literal["copy"] = "copy"
    source_path: str
    destination_path: str
