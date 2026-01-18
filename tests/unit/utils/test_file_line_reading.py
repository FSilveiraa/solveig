"""Tests for Filesystem.read_file_lines() line-based reading functionality."""

import pytest
from anyio import Path

from solveig.utils.file import Filesystem

pytestmark = pytest.mark.anyio


class TestReadFileLinesBasic:
    """Test basic file line reading operations."""

    async def test_read_all_lines_no_ranges(self, tmp_path):
        """Test reading all lines when no ranges specified."""
        test_file = tmp_path / "all_lines.txt"
        content = "line1\nline2\nline3\nline4\nline5"
        test_file.write_text(content)
        abs_path = Path(str(test_file))

        ranges = await Filesystem.read_file_lines(abs_path)
        assert len(ranges) == 1
        start, end, range_content = ranges[0]
        assert start == 1
        assert end == 5
        assert range_content == content

    async def test_read_single_range(self, tmp_path):
        """Test reading a single line range."""
        test_file = tmp_path / "single_range.txt"
        content = "line1\nline2\nline3\nline4\nline5"
        test_file.write_text(content)
        abs_path = Path(str(test_file))

        ranges = await Filesystem.read_file_lines(abs_path, [(2, 4)])
        assert len(ranges) == 1
        start, end, range_content = ranges[0]
        assert start == 2
        assert end == 4
        assert range_content == "line2\nline3\nline4"

    async def test_read_multiple_ranges(self, tmp_path):
        """Test reading multiple line ranges."""
        test_file = tmp_path / "multi_range.txt"
        content = (
            "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10"
        )
        test_file.write_text(content)
        abs_path = Path(str(test_file))

        ranges = await Filesystem.read_file_lines(abs_path, [(1, 2), (5, 6), (9, 10)])
        assert len(ranges) == 3

        assert ranges[0] == (1, 2, "line1\nline2")
        assert ranges[1] == (5, 6, "line5\nline6")
        assert ranges[2] == (9, 10, "line9\nline10")

    async def test_read_single_line_range(self, tmp_path):
        """Test reading a range with a single line."""
        test_file = tmp_path / "single_line.txt"
        content = "line1\nline2\nline3"
        test_file.write_text(content)
        abs_path = Path(str(test_file))

        ranges = await Filesystem.read_file_lines(abs_path, [(2, 2)])
        assert len(ranges) == 1
        start, end, range_content = ranges[0]
        assert start == 2
        assert end == 2
        assert range_content == "line2"

    async def test_read_range_to_end_of_file(self, tmp_path):
        """Test reading a range that extends beyond file length (clamped)."""
        test_file = tmp_path / "to_end.txt"
        content = "line1\nline2\nline3"
        test_file.write_text(content)
        abs_path = Path(str(test_file))

        ranges = await Filesystem.read_file_lines(abs_path, [(2, 100)])
        assert len(ranges) == 1
        start, end, range_content = ranges[0]
        assert start == 2
        assert end == 3  # Clamped to file length
        assert range_content == "line2\nline3"

    async def test_read_range_from_file_start(self, tmp_path):
        """Test reading from start of file."""
        test_file = tmp_path / "from_start.txt"
        content = "line1\nline2\nline3\nline4\nline5"
        test_file.write_text(content)
        abs_path = Path(str(test_file))

        ranges = await Filesystem.read_file_lines(abs_path, [(1, 3)])
        assert ranges[0] == (1, 3, "line1\nline2\nline3")


class TestReadFileLinesErrors:
    """Test error handling for line reading operations."""

    async def test_read_nonexistent_file(self):
        """Test that reading nonexistent file raises FileNotFoundError."""
        abs_path = Path("/nonexistent/file.txt")
        with pytest.raises(FileNotFoundError):
            await Filesystem.read_file_lines(abs_path)

    async def test_read_directory_raises_error(self, tmp_path):
        """Test that reading lines from directory raises IsADirectoryError."""
        abs_path = Path(str(tmp_path))
        with pytest.raises(IsADirectoryError):
            await Filesystem.read_file_lines(abs_path)

    async def test_invalid_range_start_less_than_one(self, tmp_path):
        """Test that range with start < 1 raises ValueError."""
        test_file = tmp_path / "invalid.txt"
        test_file.write_text("line1\nline2")
        abs_path = Path(str(test_file))

        with pytest.raises(ValueError, match="Start line must be >= 1"):
            await Filesystem.read_file_lines(abs_path, [(0, 2)])

    async def test_invalid_range_end_less_than_start(self, tmp_path):
        """Test that range with end < start raises ValueError."""
        test_file = tmp_path / "invalid.txt"
        test_file.write_text("line1\nline2\nline3")
        abs_path = Path(str(test_file))

        with pytest.raises(ValueError, match="End line must be >= start"):
            await Filesystem.read_file_lines(abs_path, [(3, 2)])

    async def test_invalid_range_exceeds_file(self, tmp_path):
        """Test that range starting beyond file raises ValueError."""
        test_file = tmp_path / "invalid.txt"
        test_file.write_text("line1\nline2\nline3")
        abs_path = Path(str(test_file))

        with pytest.raises(ValueError, match="exceeds file bounds"):
            await Filesystem.read_file_lines(abs_path, [(5, 6)])


class TestReadFileLinesEdgeCases:
    """Test edge cases for line reading."""

    async def test_read_preserves_line_content(self, tmp_path):
        """Test that line content is preserved including special characters."""
        test_file = tmp_path / "special.txt"
        content = "line1\ttabbed\nline2  spaced\nline3"
        test_file.write_text(content)
        abs_path = Path(str(test_file))

        ranges = await Filesystem.read_file_lines(abs_path, [(1, 3)])
        start, end, range_content = ranges[0]
        assert range_content == content

    async def test_read_empty_file_with_ranges(self, tmp_path):
        """Test reading ranges from empty file."""
        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("")
        abs_path = Path(str(empty_file))

        # Reading all lines from empty file
        ranges = await Filesystem.read_file_lines(abs_path)
        assert ranges == [(1, 0, "")]

    async def test_read_empty_file_no_newline(self, tmp_path):
        """Test reading file with content but no trailing newline."""
        test_file = tmp_path / "no_newline.txt"
        test_file.write_text("single line")
        abs_path = Path(str(test_file))

        ranges = await Filesystem.read_file_lines(abs_path)
        assert ranges == [(1, 1, "single line")]

    async def test_read_overlapping_ranges(self, tmp_path):
        """Test that overlapping ranges work (allowed for flexibility)."""
        test_file = tmp_path / "overlap.txt"
        content = "line1\nline2\nline3\nline4\nline5"
        test_file.write_text(content)
        abs_path = Path(str(test_file))

        ranges = await Filesystem.read_file_lines(abs_path, [(2, 4), (3, 5)])
        assert len(ranges) == 2
        assert ranges[0] == (2, 4, "line2\nline3\nline4")
        assert ranges[1] == (3, 5, "line3\nline4\nline5")


class TestLineReadingEncoding:
    """Test line reading with different encodings."""

    async def test_read_utf8_file(self, tmp_path):
        """Test reading UTF-8 encoded file."""
        test_file = tmp_path / "utf8.txt"
        content = "Hello\nWorld\n世界"
        test_file.write_text(content, encoding="utf-8")
        abs_path = Path(str(test_file))

        ranges = await Filesystem.read_file_lines(abs_path, encoding="utf-8")
        assert len(ranges) == 1
        _, _, range_content = ranges[0]
        assert range_content == content.rstrip("\n")

    async def test_count_lines_with_encoding(self, tmp_path):
        """Test counting lines with specified encoding."""
        test_file = tmp_path / "encoded.txt"
        test_file.write_text("line1\nline2\nline3", encoding="utf-8")
        abs_path = Path(str(test_file))

        count = await Filesystem._count_lines(abs_path, encoding="utf-8")
        assert count == 3
