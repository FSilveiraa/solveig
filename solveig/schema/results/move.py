from __future__ import annotations

from solveig.utils.file import SolveigPath

from .base import RequirementResult


class MoveResult(RequirementResult):
    source_path: SolveigPath
    destination_path: SolveigPath
