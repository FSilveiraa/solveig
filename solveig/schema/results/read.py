from __future__ import annotations

from pathlib import Path

from ...utils.file import Metadata
from .base import RequirementResult


class ReadResult(RequirementResult):
    # The requested path can be different from the canonical one in metadata
    path: str | Path
    metadata: Metadata | None = None
    content: str | None = None

    def to_openai(self):
        data = super().to_openai()
        if self.metadata is not None:
            data["metadata"] = self.metadata.to_openai()
        return data
