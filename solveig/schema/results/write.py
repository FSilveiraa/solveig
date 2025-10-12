from __future__ import annotations

from .base import RequirementResult
from solveig.utils.file import SolveigPath


class WriteResult(RequirementResult):
    path: SolveigPath
