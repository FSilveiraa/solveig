from __future__ import annotations

from solveig.utils.file import SolveigPath

from .base import RequirementResult


class DeleteResult(RequirementResult):
    path: SolveigPath
