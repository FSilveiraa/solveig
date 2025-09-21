"""
Tests for solveig.utils.filesystem module.

The requirement tests were first implemented and they already test the
actual file operations, so for now I'm focused on testing the data class
and size parsing.
"""

from datetime import datetime
from pathlib import Path

import pytest

from solveig.utils.file import Metadata
from solveig.utils.misc import parse_human_readable_size


class TestSizeNotationParsing:
    """Test size notation parsing functionality."""

    def test_parse_int_bytes(self):
        """Test parsing integer bytes."""
        assert parse_human_readable_size(1024) == 1024
        assert parse_human_readable_size("1024") == 1024

    def test_parse_size_units(self):
        """Test parsing various size units."""
        assert parse_human_readable_size("1 KB") == 1000
        assert parse_human_readable_size("1 MB") == 1000000
        assert parse_human_readable_size("1 GB") == 1000000000
        assert parse_human_readable_size("1 KiB") == 1024
        assert parse_human_readable_size("1 MiB") == 1024**2
        assert parse_human_readable_size("1 GiB") == 1024**3

    def test_parse_decimal_sizes(self):
        """Test parsing decimal sizes."""
        assert parse_human_readable_size("1.5 KB") == 1500
        assert parse_human_readable_size("2.5 GiB") == int(2.5 * 1024**3)

    def test_parse_invalid_unit(self):
        """Test parsing invalid units raises ValueError."""
        with pytest.raises(ValueError, match="not a valid disk size"):
            parse_human_readable_size("1 XB")

    def test_parse_invalid_format(self):
        """Test parsing invalid format raises ValueError."""
        with pytest.raises(ValueError, match="not a valid disk size"):
            parse_human_readable_size("invalid")
        with pytest.raises(ValueError, match="not a valid disk size"):
            parse_human_readable_size("1.2.3 GB")

    def test_parse_none_returns_zero(self):
        """Test parsing None returns 0."""
        assert parse_human_readable_size(None) == 0


class TestMetadata:
    """Test Metadata dataclass."""

    def test_metadata_creation(self):
        """Test creating metadata object."""
        metadata = Metadata(
            owner_name="test_user",
            group_name="test_group",
            path=Path("/test/file.txt"),
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
