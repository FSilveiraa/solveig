from __future__ import annotations

from pathlib import Path

from ...utils.file import Metadata
from .base import RequirementResult


class ReadResult(RequirementResult):
    path: str | Path
    metadata: Metadata | None = None
    # For files
    content: str | None = None
    # For directories
    directory_listing: dict[Path, Metadata] | None = None

    def to_openai(self):
        data = super().to_openai()
        if data.get("directory_listing"):
            data["directory_listing"] = {
                str(path): metadata
                for path, metadata in data["directory_listing"].items()
            }
        return data
