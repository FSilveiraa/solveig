"""Integration tests for WriteRequirement."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from solveig.schema.requirements import WriteRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface

# Mark all tests in this module to skip file mocking
pytestmark = pytest.mark.no_file_mocking


class TestWriteValidation:
    """Test WriteRequirement validation patterns."""

    def test_path_validation_patterns(self):
        """Test path validation for empty, whitespace, and valid paths."""
        extra_kwargs = {"is_directory": False, "comment": "test"}

        # Empty path should fail
        with pytest.raises(ValidationError) as exc_info:
            WriteRequirement(path="", **extra_kwargs)
        error_msg = str(exc_info.value.errors()[0]["msg"])
        assert "Empty path" in error_msg or "Field required" in error_msg

        # Whitespace path should fail
        with pytest.raises(ValidationError):
            WriteRequirement(path="   \t\n   ", **extra_kwargs)

        # Valid path should strip whitespace
        req = WriteRequirement(path="  /valid/path  ", **extra_kwargs)
        assert req.path == "/valid/path"


class TestWriteDisplay:
    """Test WriteRequirement display methods."""

    @pytest.mark.anyio
    async def test_write_requirement_display(self):
        """Test WriteRequirement display for files and directories."""
        # Test file creation display
        file_req = WriteRequirement(
            path="/test/file.txt",
            is_directory=False,
            content="test",
            comment="Create file",
        )
        interface = MockInterface()

        # Test file display (summary mode)
        await file_req.display_header(interface)
        output = interface.get_all_output()
        assert "Create file" in output
        assert "🗎  /test/file.txt" in output
        interface.clear()

        # Test directory creation display (summary mode)
        dir_req = WriteRequirement(
            path="/test/dir", is_directory=True, comment="Create directory"
        )
        await dir_req.display_header(interface)
        output = interface.get_all_output()
        assert "🗁  /test/dir" in output
        interface.clear()

        # Test get_description
        description = WriteRequirement.get_description()
        assert "write(comment, path, is_directory, content=null)" in description


class TestWriteFileOperations:
    """Test WriteRequirement with real file creation."""

    @pytest.mark.anyio
    async def test_create_new_file_with_content(self):
        """Test creating a new file with content."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "new_file.txt"
            test_content = "This is new content created by integration test"

            req = WriteRequirement(
                path=str(test_file),
                is_directory=False,
                content=test_content,
                comment="Create new file",
            )
            mock_interface = MockInterface()
            mock_interface.user_inputs.append("y")

            result = await req.actually_solve(
                config=DEFAULT_CONFIG, interface=mock_interface
            )

            # Verify write succeeded
            assert result.accepted
            assert result.error is None

            # Verify file was actually created
            assert test_file.exists()
            assert test_file.read_text() == test_content

    @pytest.mark.anyio
    async def test_create_directory_structure(self):
        """Test creating nested directory structure."""
        mock_interface = MockInterface()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            new_dir = temp_path / "nested" / "deep" / "directory"

            req = WriteRequirement(
                path=str(new_dir), is_directory=True, comment="Create nested directory"
            )
            mock_interface.user_inputs.append("y")

            result = await req.actually_solve(
                config=DEFAULT_CONFIG, interface=mock_interface
            )

            # Verify directory creation
            assert result.accepted
            assert new_dir.exists()
            assert new_dir.is_dir()

    @pytest.mark.anyio
    async def test_overwrite_existing_file_warning(self):
        """Test that overwriting existing files shows warning."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            existing_file = temp_path / "existing.txt"
            existing_file.write_text("Original content")

            req = WriteRequirement(
                path=str(existing_file),
                is_directory=False,
                content="New content",
                comment="Overwrite file",
            )
            mock_interface = MockInterface()
            mock_interface.user_inputs.append("y")

            result = await req.solve(config=DEFAULT_CONFIG, interface=mock_interface)

            # Should warn about existing path
            warning_calls = [
                call
                for call in mock_interface.outputs
                if any(
                    sig in call.lower() for sig in {"warning", "⚠", "already exists"}
                )
            ]
            assert len(warning_calls) > 0

            # File should be overwritten
            assert result.accepted
            assert existing_file.read_text() == "New content"

    @pytest.mark.anyio
    async def test_write_declined(self):
        """Test when user declines write operation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "declined_write.txt"

            write_req = WriteRequirement(
                path=str(test_file),
                is_directory=False,
                content="test",
                comment="Write declined",
            )
            interface = MockInterface()
            interface.set_user_inputs(["n"])  # Decline operation
            result = await write_req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is False


class TestWriteErrorHandling:
    """Test WriteRequirement error handling."""

    def test_error_result_creation(self):
        """Test create_error_result method for WriteRequirement."""
        req = WriteRequirement(path="/test.txt", is_directory=False, comment="Test")
        error_result = req.create_error_result("Test error", accepted=False)
        assert error_result.requirement == req
        assert error_result.accepted is False
        assert error_result.error == "Test error"

    @pytest.mark.anyio
    async def test_write_encoding_error_handling(self):
        """Test WriteRequirement handling of encoding errors."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "error_file.txt"

            write_req = WriteRequirement(
                path=str(test_file),
                is_directory=False,
                content="test content",
                comment="Write with error",
            )
            interface = MockInterface()

            # Mock Filesystem.write_file to raise an encoding exception
            with patch("solveig.utils.file.Filesystem.write_file") as mock_write:
                mock_write.side_effect = UnicodeEncodeError(
                    "utf-8", "", 0, 1, "test error"
                )

                interface.set_user_inputs(["y"])  # Accept operation
                result = await write_req.solve(DEFAULT_CONFIG, interface)

                # Should handle encoding error
                assert result.accepted is False
                assert "Encoding error" in result.error
                output = interface.get_all_output()
                assert "Found error when writing file" in output


class TestWritePathSecurity:
    """Test WriteRequirement path security and validation."""

    @pytest.mark.anyio
    async def test_path_expansion_in_write_requirements(self):
        """Test that path expansion is handled properly in WriteRequirement."""
        # Create tempfile in real home directory to test expansion
        with tempfile.NamedTemporaryFile(
            dir=Path.home(),
            prefix=".solveig_test_expansion_",
            suffix=".txt",
            delete=False,
        ) as temp_file:
            temp_file_path = Path(temp_file.name)

        try:
            # Use ~ path that should expand to the tempfile
            tilde_path = f"~/{temp_file_path.name}"

            req = WriteRequirement(path=tilde_path, is_directory=False, comment="Test")
            interface = MockInterface()
            interface.set_user_inputs(
                ["n", "n"]
            )  # Decline metadata, decline error sending
            result = await req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is False

            # Verify path expansion happened - should contain home path, not ~
            assert "~" not in str(result.path)
            assert str(Path.home()) in str(result.path)
            assert temp_file_path.name in str(result.path)
        finally:
            # Clean up tempfile
            if temp_file_path.exists():
                temp_file_path.unlink()
