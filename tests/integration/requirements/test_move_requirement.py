"""Integration tests for MoveRequirement."""

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from solveig.schema.requirements import MoveRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface

# Mark all tests in this module to skip file mocking
pytestmark = pytest.mark.no_file_mocking


class TestMoveValidation:
    """Test MoveRequirement validation patterns."""

    def test_two_path_validation(self):
        """Test validation for requirements with source and destination paths."""
        # Empty source path should fail
        with pytest.raises(ValidationError) as exc_info:
            MoveRequirement(source_path="", destination_path="/dest", comment="test")
        assert exc_info.value.errors()[0]["loc"] == ("source_path",)

        # Empty destination path should fail
        with pytest.raises(ValidationError) as exc_info:
            MoveRequirement(source_path="/src", destination_path="", comment="test")
        assert exc_info.value.errors()[0]["loc"] == ("destination_path",)


class TestMoveDisplay:
    """Test MoveRequirement display methods."""

    @pytest.mark.anyio
    async def test_move_requirement_display(self):
        """Test MoveRequirement display patterns."""
        req = MoveRequirement(
            source_path="/src/file.txt",
            destination_path="/dst/file.txt",
            comment="Move file",
        )

        interface = MockInterface()
        await req.display_header(interface)
        output = interface.get_all_output()

        assert "Move file" in output
        assert "/src/file.txt" in output
        assert "/dst/file.txt" in output

        # Test get_description
        description = MoveRequirement.get_description()
        assert "move(comment, source_path, destination_path)" in description


class TestMoveFileOperations:
    """Test MoveRequirement with real file moves."""

    @pytest.mark.anyio
    async def test_move_file(self):
        """Test moving a file from one location to another."""
        mock_interface = MockInterface()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_file = temp_path / "source.txt"
            dest_file = temp_path / "destination.txt"
            test_content = "Content to be moved"

            # Create source file
            source_file.write_text(test_content)

            req = MoveRequirement(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Move file",
            )
            mock_interface = MockInterface()
            mock_interface.user_inputs.append("y")

            result = await req.actually_solve(
                config=DEFAULT_CONFIG, interface=mock_interface
            )

            # Verify move succeeded
            assert result.accepted
            assert not source_file.exists()  # Source should be gone
            assert dest_file.exists()  # Destination should exist
            assert dest_file.read_text() == test_content

            # Verify paths in result are absolute
            assert Path(str(result.source_path)).is_absolute()
            assert Path(str(result.destination_path)).is_absolute()

    @pytest.mark.anyio
    async def test_move_directory(self):
        """Test moving an entire directory."""
        mock_interface = MockInterface()
        mock_interface.user_inputs.append("y")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_dir = temp_path / "source_dir"
            dest_dir = temp_path / "dest_dir"

            # Create source directory with files
            source_dir.mkdir()
            (source_dir / "file1.txt").write_text("File 1 content")
            (source_dir / "file2.txt").write_text("File 2 content")

            req = MoveRequirement(
                source_path=str(source_dir),
                destination_path=str(dest_dir),
                comment="Move directory",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, mock_interface)

            # Verify directory move
            assert result.accepted
            assert not source_dir.exists()
            assert dest_dir.exists()
            assert (dest_dir / "file1.txt").read_text() == "File 1 content"
            assert (dest_dir / "file2.txt").read_text() == "File 2 content"

    @pytest.mark.anyio
    async def test_move_nonexistent_source(self):
        """Test moving a file that doesn't exist."""
        mock_interface = MockInterface()
        mock_interface.user_inputs.append("y")
        req = MoveRequirement(
            source_path="/nonexistent/source.txt",
            destination_path="/tmp/dest.txt",
            comment="Move missing file",
        )

        result = await req.actually_solve(DEFAULT_CONFIG, mock_interface)

        # Should fail gracefully
        assert not result.accepted
        assert result.error is not None

    @pytest.mark.anyio
    async def test_move_declined(self):
        """Test when user declines move operation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_file = temp_path / "source.txt"
            dest_file = temp_path / "moved.txt"
            source_file.write_text("source content")

            req = MoveRequirement(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Move file",
            )
            interface = MockInterface()
            interface.set_user_inputs(["n"])
            result = await req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is False


class TestMoveErrorHandling:
    """Test MoveRequirement error handling."""

    def test_error_result_creation(self):
        """Test create_error_result method for MoveRequirement."""
        req = MoveRequirement(
            source_path="/src.txt", destination_path="/dst.txt", comment="Test"
        )
        error_result = req.create_error_result("Test error", accepted=False)
        assert error_result.requirement == req
        assert error_result.accepted is False
        assert error_result.error == "Test error"
