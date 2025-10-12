from __future__ import annotations

from ...utils.file import Metadata
from .base import RequirementResult
from solveig.utils.file import SolveigPath


class ReadResult(RequirementResult):
    # The requested path can be different from the canonical one in metadata
    path: SolveigPath
    metadata: Metadata | None = None
    content: str | None = None
