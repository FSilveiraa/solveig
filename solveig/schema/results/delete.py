from __future__ import annotations

from .base import RequirementResult
from solveig.utils.file import SolveigPath


class DeleteResult(RequirementResult):
    path: SolveigPath
