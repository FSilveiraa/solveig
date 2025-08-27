from __future__ import annotations

from pathlib import Path

from .base import RequirementResult


class TreeResult(RequirementResult):
    path: str | Path
    tree_output: str
    total_files: int = 0
    total_dirs: int = 0
    max_depth_reached: bool = False
