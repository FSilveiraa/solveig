"""
Tests for solveig.utils.filesystem module.

The tool tests were first implemented and they already test the actual file
operations, so this file focuses on testing the metadata class.
"""

from datetime import datetime

import pytest

from solveig.utils.file import FileMetadata

pytestmark = pytest.mark.anyio


class TestMetadata:
    """Test FileMetadata dataclass."""

    async def test_metadata_creation(self):
        """Test creating metadata object."""
        metadata = FileMetadata(
            owner_name="test_user",
            group_name="test_group",
            path="/test/file.txt",
            size=1024,
            modified_time=int(
                datetime.fromisoformat("2024-01-01T12:00:00").timestamp()
            ),
            is_directory=False,
            is_readable=True,
            is_writable=True,
        )
        assert metadata.owner_name == "test_user"
        assert metadata.size == 1024
        assert metadata.is_directory is False
