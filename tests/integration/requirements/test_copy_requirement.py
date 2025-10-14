"""Integration tests for CopyRequirement."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from solveig.schema.requirements import CopyRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface

# Mark all tests in this module to skip file mocking
pytestmark = pytest.mark.no_file_mocking


class TestCopyValidation:
    """Test CopyRequirement validation patterns."""

    def test_two_path_validation(self):
        """Test validation for requirements with source and destination paths."""
        # Empty source path should fail
        with pytest.raises(ValidationError) as exc_info:
            CopyRequirement(source_path="", destination_path="/dest", comment="test")
        assert exc_info.value.errors()[0]["loc"] == ("source_path",)

        # Empty destination path should fail
        with pytest.raises(ValidationError) as exc_info:
            CopyRequirement(source_path="/src", destination_path="", comment="test")
        assert exc_info.value.errors()[0]["loc"] == ("destination_path",)


class TestCopyDisplay:
    """Test CopyRequirement display methods."""

    @pytest.mark.anyio
    async def test_copy_requirement_display(self):
        """Test CopyRequirement display patterns."""
        req = CopyRequirement(
            source_path="/src/file.txt",
            destination_path="/dst/file.txt",
            comment="Copy file",
        )

        interface = MockInterface()
        await req.display_header(interface)
        output = interface.get_all_output()

        assert "Copy file" in output
        assert "/src/file.txt" in output
        assert "/dst/file.txt" in output

        # Test get_description
        description = CopyRequirement.get_description()
        assert "copy(comment, source_path, destination_path)" in description


class TestCopyFileOperations:
    """Test CopyRequirement with real file copying."""

    @pytest.mark.anyio
    async def test_copy_file(self):
        """Test copying a file to new location."""
        mock_interface = MockInterface()
        mock_interface.user_inputs.append("y")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_file = temp_path / "original.txt"
            dest_file = temp_path / "copy.txt"
            test_content = "Content to be copied"

            # Create source file
            source_file.write_text(test_content)

            req = CopyRequirement(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Copy file",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, mock_interface)

            # Verify copy succeeded
            assert result.accepted
            assert source_file.exists()  # Source should remain
            assert dest_file.exists()  # Destination should exist
            assert source_file.read_text() == test_content
            assert dest_file.read_text() == test_content

    @pytest.mark.anyio
    async def test_copy_directory_tree(self):
        """Test copying an entire directory tree."""
        mock_interface = MockInterface()
        mock_interface.user_inputs.append("y")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_dir = temp_path / "source"
            dest_dir = temp_path / "destination"

            # Create complex directory structure
            source_dir.mkdir()
            (source_dir / "file.txt").write_text("Root file")
            (source_dir / "subdir").mkdir()
            (source_dir / "subdir" / "nested.txt").write_text("Nested file")

            req = CopyRequirement(
                source_path=str(source_dir),
                destination_path=str(dest_dir),
                comment="Copy directory tree",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, mock_interface)

            # Verify directory tree copy
            assert result.accepted
            assert source_dir.exists()  # Original remains
            assert dest_dir.exists()  # Copy created
            assert (dest_dir / "file.txt").read_text() == "Root file"
            assert (dest_dir / "subdir" / "nested.txt").read_text() == "Nested file"

    @pytest.mark.anyio
    async def test_copy_declined(self):
        """Test when user declines copy operation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_file = temp_path / "source.txt"
            dest_file = temp_path / "copy.txt"
            source_file.write_text("source content")

            req = CopyRequirement(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Copy file",
            )
            interface = MockInterface()
            interface.set_user_inputs(["n"])
            result = await req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is False


class TestCopyErrorHandling:
    """Test CopyRequirement error handling."""

    def test_error_result_creation(self):
        """Test create_error_result method for CopyRequirement."""
        req = CopyRequirement(
            source_path="/src.txt", destination_path="/dst.txt", comment="Test"
        )
        error_result = req.create_error_result("Test error", accepted=False)
        assert error_result.requirement == req
        assert error_result.accepted is False
        assert error_result.error == "Test error"

    @pytest.mark.anyio
    async def test_copy_with_insufficient_space_error(self):
        """Test CopyRequirement handling real disk space errors."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_file = temp_path / "source.txt"
            dest_file = temp_path / "dest.txt"
            source_file.write_text("content")

            copy_req = CopyRequirement(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Copy with space error",
            )
            interface = MockInterface()

            # Mock Filesystem.copy to raise a disk space exception
            with patch("solveig.utils.file.Filesystem.copy") as mock_copy:
                mock_copy.side_effect = OSError("No space left on device")

                interface.set_user_inputs(["y"])  # Accept operation
                result = await copy_req.solve(DEFAULT_CONFIG, interface)

                # Should handle disk space error
                assert result.accepted is False
                assert "No space left on device" in result.error
                output = interface.get_all_output()
                assert "Found error when copying" in output
