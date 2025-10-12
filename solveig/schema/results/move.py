from __future__ import annotations

from .base import RequirementResult
from solveig.utils.file import SolveigPath


class MoveResult(RequirementResult):
    source_path: SolveigPath
    destination_path: SolveigPath
