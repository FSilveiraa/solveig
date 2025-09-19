from __future__ import annotations

from pathlib import PurePath

from ...utils.file import Metadata
from .base import RequirementResult


class ReadResult(RequirementResult):
    # The requested path can be different from the canonical one in metadata
    path: str | PurePath
    metadata: Metadata | None = None
    content: str | None = None
