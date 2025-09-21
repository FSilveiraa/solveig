"""Comprehensive integration tests for all requirement types.

These tests exercise the full stack from requirement validation to actual file operations,
using real files in temporary directories. Only user interactions are mocked.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

# Mark all tests in this module to skip file mocking
pytestmark = pytest.mark.no_file_mocking

from solveig.schema.requirements import (
    CommandRequirement,
    CopyRequirement,
    DeleteRequirement,
    MoveRequirement,
    ReadRequirement,
    WriteRequirement,
)
from tests.mocks import DEFAULT_CONFIG, MockInterface


class TestRequirementValidation:
    """Test validation patterns across all requirements (no filesystem needed)."""

    def test_path_validation_patterns(self):
        """Test path validation for empty, whitespace, and valid paths."""
        # Test single-path requirements
        single_path_requirements = [
            (ReadRequirement, {"metadata_only": False, "comment": "test"}),
            (WriteRequirement, {"is_directory": False, "comment": "test"}),
            (DeleteRequirement, {"comment": "test"}),
        ]

        for req_class, extra_kwargs in single_path_requirements:
            # Empty path should fail
            with pytest.raises(ValidationError) as exc_info:
                req_class(path="", **extra_kwargs)
            error_msg = str(exc_info.value.errors()[0]["msg"])
            assert "Empty path" in error_msg or "Field required" in error_msg

            # Whitespace path should fail
            with pytest.raises(ValidationError):
                req_class(path="   \t\n   ", **extra_kwargs)

            # Valid path should strip whitespace
            req = req_class(path="  /valid/path  ", **extra_kwargs)
            assert req.path == "/valid/path"

    def test_command_validation_patterns(self):
        """Test command validation for empty, whitespace, None, and valid commands."""
        # Empty command should fail
        with pytest.raises(ValidationError) as exc_info:
            CommandRequirement(command="", comment="test")
        assert "Empty command" in str(exc_info.value.errors()[0]["msg"])

        # Whitespace command should fail
        with pytest.raises(ValidationError):
            CommandRequirement(command="   \n\t  ", comment="test")

        # None command should fail
        with pytest.raises(ValidationError):
            CommandRequirement(command=None, comment="test")

        # Valid command should strip whitespace
        req = CommandRequirement(command="  ls -la  ", comment="test")
        assert req.command == "ls -la"

    def test_two_path_validation(self):
        """Test validation for requirements with source and destination paths."""
        two_path_requirements = [MoveRequirement, CopyRequirement]

        for req_class in two_path_requirements:
            # Empty source path should fail
            with pytest.raises(ValidationError) as exc_info:
                req_class(source_path="", destination_path="/dest", comment="test")
            assert exc_info.value.errors()[0]["loc"] == ("source_path",)

            # Empty destination path should fail
            with pytest.raises(ValidationError) as exc_info:
                req_class(source_path="/src", destination_path="", comment="test")
            assert exc_info.value.errors()[0]["loc"] == ("destination_path",)


class TestRequirementDisplay:
    """Test display methods for all requirements."""

    def test_command_requirement_display(self):
        """Test CommandRequirement display and description."""
        req = CommandRequirement(command="echo test", comment="Test echo command")
        interface = MockInterface()

        # Test display header (summary mode)
        req.display_header(interface, detailed=False)
        output = interface.get_all_output()
        assert "Test echo command" in output
        interface.clear()

        # Test display header (detailed mode)
        req.display_header(interface, detailed=True)
        output = interface.get_all_output()
        assert "Test echo command" in output
        assert "echo test" in output  # Command should be shown in text block

        # Test get_description
        description = CommandRequirement.get_description()
        assert "command(command)" in description
        assert "execute shell commands" in description

    def test_read_requirement_display(self):
        """Test ReadRequirement display and description."""
        req = ReadRequirement(
            path="/test/file.txt", metadata_only=False, comment="Read test file"
        )
        interface = MockInterface()

        # Test display header (summary mode)
        req.display_header(interface, detailed=False)
        output = interface.get_all_output()
        assert "Read test file" in output
        assert "🗎  /test/file.txt" in output
        interface.clear()

        # Test display header (detailed mode - same as summary for reads)
        req.display_header(interface, detailed=True)
        output = interface.get_all_output()
        assert "Read test file" in output
        assert "🗎  /test/file.txt" in output

        # Test get_description
        description = ReadRequirement.get_description()
        assert "read(path, metadata_only)" in description

    def test_write_requirement_display(self):
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
        file_req.display_header(interface, detailed=False)
        output = interface.get_all_output()
        assert "Create file" in output
        assert "🗎  /test/file.txt" in output
        interface.clear()

        # Test file display (detailed mode - should show content)
        file_req.display_header(interface, detailed=True)
        output = interface.get_all_output()
        assert "Create file" in output
        assert "test" in output  # Content should be shown in text block
        interface.clear()

        # Test directory creation display (summary mode)
        dir_req = WriteRequirement(
            path="/test/dir", is_directory=True, comment="Create directory"
        )
        dir_req.display_header(interface, detailed=False)
        output = interface.get_all_output()
        assert "🗁  /test/dir" in output
        interface.clear()

        # Test directory display (detailed mode - no content to show)
        dir_req.display_header(interface, detailed=True)
        output = interface.get_all_output()
        assert "🗁  /test/dir" in output

        # Test get_description
        description = WriteRequirement.get_description()
        assert "write(path, is_directory" in description

    def test_delete_requirement_display(self):
        """Test DeleteRequirement display and warnings."""
        req = DeleteRequirement(path="/test/delete_me.txt", comment="Delete test file")

        # Test that both detailed modes produce same output for delete
        interface_basic = MockInterface()
        req.display_header(interface_basic, detailed=False)
        basic_output = interface_basic.get_all_output()

        interface_detailed = MockInterface()
        req.display_header(interface_detailed, detailed=True)
        detailed_output = interface_detailed.get_all_output()

        assert basic_output == detailed_output
        assert "Delete test file" in basic_output
        assert "/test/delete_me.txt" in basic_output
        assert "permanent" in basic_output.lower()

        # Test get_description
        description = DeleteRequirement.get_description()
        assert "delete(path)" in description

    def test_copy_requirement_display(self):
        """Test CopyRequirement display patterns."""
        req = CopyRequirement(
            source_path="/src/file.txt",
            destination_path="/dst/file.txt",
            comment="Copy file",
        )

        # Test that both detailed modes produce same output for copy
        interface_basic = MockInterface()
        req.display_header(interface_basic, detailed=False)
        basic_output = interface_basic.get_all_output()

        interface_detailed = MockInterface()
        req.display_header(interface_detailed, detailed=True)
        detailed_output = interface_detailed.get_all_output()

        assert basic_output == detailed_output
        assert "Copy file" in basic_output
        assert "/src/file.txt" in basic_output
        assert "/dst/file.txt" in basic_output

        # Test get_description
        description = CopyRequirement.get_description()
        assert "copy(source_path, destination_path)" in description

    def test_move_requirement_display(self):
        """Test MoveRequirement display patterns."""
        req = MoveRequirement(
            source_path="/src/file.txt",
            destination_path="/dst/file.txt",
            comment="Move file",
        )

        # Test that both detailed modes produce same output for move
        interface_basic = MockInterface()
        req.display_header(interface_basic, detailed=False)
        basic_output = interface_basic.get_all_output()

        interface_detailed = MockInterface()
        req.display_header(interface_detailed, detailed=True)
        detailed_output = interface_detailed.get_all_output()

        assert basic_output == detailed_output
        assert "Move file" in basic_output
        assert "/src/file.txt" in basic_output
        assert "/dst/file.txt" in basic_output

        # Test get_description
        description = MoveRequirement.get_description()
        assert "move(source_path, destination_path)" in description


class TestCommandRequirement:
    """Test CommandRequirement with real subprocess execution."""

    @pytest.mark.no_subprocess_mocking
    def test_successful_command_execution(self):
        """Test successful command execution."""
        req = CommandRequirement(command="echo test", comment="Test echo command")
        interface = MockInterface()

        # Test: user accepts command and output
        interface.set_user_inputs(["y", "y"])
        result = req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is True
        assert result.success is True
        assert "test" in result.stdout

    def test_command_declined(self):
        """Test when user declines command execution."""
        req = CommandRequirement(command="echo test", comment="Test echo command")
        interface = MockInterface()

        interface.set_user_inputs(["n"])
        result = req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is False

    @pytest.mark.no_subprocess_mocking
    def test_command_with_error_output(self):
        """Test command that produces error output."""
        # Use a predictable failing command that works cross-platform
        req = CommandRequirement(
            command="python -c \"import sys; sys.stderr.write('test error\\n'); sys.exit(1)\"",
            comment="Command with error",
        )
        interface = MockInterface()
        interface.set_user_inputs(["y", "y"])  # Accept command and output

        result = req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is True
        assert result.success is True  # Shell execution succeeded (ran the command)
        assert "test error" in result.error  # Should have specific error content

    def test_empty_command_execution(self):
        """Test _execute_command with empty command."""
        req = CommandRequirement(command="echo test", comment="Test")
        req.command = None  # Force empty command

        with pytest.raises(ValueError, match="Empty command"):
            req._execute_command(DEFAULT_CONFIG)


class TestReadRequirement:
    """Test ReadRequirement with real file I/O."""

    def test_read_file_with_tilde_path(self):
        """Test reading a file using tilde path expansion."""
        # Create tempfile in real home directory to test tilde expansion
        with tempfile.NamedTemporaryFile(
            dir=Path.home(),
            prefix=".solveig_test_read_",
            suffix=".txt",
            delete=False,
            mode="w",
        ) as temp_file:
            test_content = "Hello from tilde expansion test!"
            temp_file.write(test_content)
            temp_file_path = Path(temp_file.name)

        try:
            # Use ~ path that should expand to the tempfile we created
            tilde_path = f"~/{temp_file_path.name}"

            mock_interface = MockInterface()
            mock_interface.user_inputs.extend(["y", "y"])

            # Create requirement with tilde path
            req = ReadRequirement(
                path=tilde_path,
                metadata_only=False,
                comment="Test tilde expansion",
            )

            result = req.actually_solve(config=DEFAULT_CONFIG, interface=mock_interface)

            # Verify result
            assert result.accepted
            assert result.content == test_content
            assert result.metadata is not None
            assert temp_file_path.name == result.metadata.path.name

            # Verify path expansion worked - should resolve to absolute path without ~
            assert "~" not in str(result.path)
            assert str(result.path) == str(temp_file_path.resolve())
        finally:
            # Clean up tempfile
            if temp_file_path.exists():
                temp_file_path.unlink()

    def test_read_directory_listing(self):
        """Test reading directory with real files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            mock_interface = MockInterface()
            mock_interface.user_inputs.append("y")

            # Create test files
            (temp_path / "file1.txt").write_text("Content 1")
            (temp_path / "file2.py").write_text("print('hello')")
            (temp_path / "subdir").mkdir()
            (temp_path / "subdir" / "nested.txt").write_text("Nested content")

            # Test directory read
            req = ReadRequirement(
                path=str(temp_path), metadata_only=True, comment="Read directory"
            )

            result = req.actually_solve(config=DEFAULT_CONFIG, interface=mock_interface)

            # Verify directory listing
            assert result.accepted
            assert result.metadata.listing is not None
            assert len(result.metadata.listing) == 3  # file1.txt, file2.py, subdir

            # Check specific files in listing
            filenames = {item.name for item in result.metadata.listing}
            assert "file1.txt" in filenames
            assert "file2.py" in filenames
            assert "subdir" in filenames

    def test_read_nonexistent_file(self):
        """Test reading a file that doesn't exist."""
        req = ReadRequirement(
            path="/nonexistent/file.txt",
            metadata_only=False,
            comment="Read missing file",
        )
        mock_interface = MockInterface()

        result = req.actually_solve(config=DEFAULT_CONFIG, interface=mock_interface)

        # Should fail gracefully
        assert not result.accepted
        assert result.error is not None
        assert "does not exist" in result.error.lower()

    def test_read_permission_denied(self):
        """Test reading a file with insufficient permissions."""
        mock_interface = MockInterface()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            restricted_file = temp_path / "restricted.txt"
            restricted_file.write_text("Secret content")

            # Remove read permissions
            restricted_file.chmod(0o000)

            try:
                req = ReadRequirement(
                    path=str(restricted_file),
                    metadata_only=False,
                    comment="Read restricted file",
                )

                result = req.actually_solve(
                    config=DEFAULT_CONFIG, interface=mock_interface
                )

                # Should fail gracefully
                assert not result.accepted
                assert result.error is not None
                assert (
                    "Permission denied" in result.error
                    or "not readable" in result.error
                )

            finally:
                # Restore permissions for cleanup
                restricted_file.chmod(0o644)

    def test_read_user_decline_scenarios(self):
        """Test various user decline scenarios for read operations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "readable.txt"
            test_file.write_text("test content")

            # Test: Decline read operation entirely
            read_req = ReadRequirement(
                path=str(test_file),
                metadata_only=False,
                comment="Read declined",
            )
            interface = MockInterface()
            interface.set_user_inputs(
                ["n", "n"]
            )  # Decline metadata, decline error sending

            result = read_req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is False


class TestWriteRequirement:
    """Test WriteRequirement with real file creation."""

    def test_create_new_file_with_content(self):
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

            result = req.actually_solve(config=DEFAULT_CONFIG, interface=mock_interface)

            # Verify write succeeded
            assert result.accepted
            assert result.error is None

            # Verify file was actually created
            assert test_file.exists()
            assert test_file.read_text() == test_content

    def test_create_directory_structure(self):
        """Test creating nested directory structure."""
        mock_interface = MockInterface()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            new_dir = temp_path / "nested" / "deep" / "directory"

            req = WriteRequirement(
                path=str(new_dir), is_directory=True, comment="Create nested directory"
            )
            mock_interface.user_inputs.append("y")

            result = req.actually_solve(config=DEFAULT_CONFIG, interface=mock_interface)

            # Verify directory creation
            assert result.accepted
            assert new_dir.exists()
            assert new_dir.is_dir()

    def test_overwrite_existing_file_warning(self):
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

            result = req.actually_solve(config=DEFAULT_CONFIG, interface=mock_interface)

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

    def test_write_declined(self):
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
            result = write_req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is False


class TestDeleteRequirement:
    """Test DeleteRequirement with real file deletion."""

    def test_delete_file(self):
        """Test deleting a file."""
        mock_interface = MockInterface()
        mock_interface.user_inputs.append("y")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "to_delete.txt"
            test_file.write_text("This file will be deleted")

            assert test_file.exists()  # Verify file exists before deletion

            req = DeleteRequirement(path=str(test_file), comment="Delete test file")

            result = req.actually_solve(DEFAULT_CONFIG, mock_interface)

            # Verify deletion
            assert result.accepted
            assert not test_file.exists()  # File should be gone

    def test_delete_directory_tree(self):
        """Test deleting an entire directory tree."""
        mock_interface = MockInterface()
        mock_interface.user_inputs.append("y")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_dir = temp_path / "dir_to_delete"

            # Create directory with nested content
            test_dir.mkdir()
            (test_dir / "file1.txt").write_text("File 1")
            (test_dir / "subdir").mkdir()
            (test_dir / "subdir" / "file2.txt").write_text("File 2")

            req = DeleteRequirement(path=str(test_dir), comment="Delete directory tree")

            result = req.actually_solve(DEFAULT_CONFIG, mock_interface)

            # Verify directory deletion
            assert result.accepted
            assert not test_dir.exists()  # Entire tree should be gone

    def test_delete_nonexistent_file(self):
        """Test deleting a file that doesn't exist."""
        mock_interface = MockInterface()
        mock_interface.user_inputs.append("y")
        req = DeleteRequirement(
            path="/nonexistent/file.txt", comment="Delete missing file"
        )

        result = req.actually_solve(DEFAULT_CONFIG, mock_interface)

        # Should fail gracefully
        assert not result.accepted
        assert result.error is not None

    def test_delete_declined(self):
        """Test when user declines delete operation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "to_delete.txt"
            test_file.write_text("content")

            delete_req = DeleteRequirement(
                path=str(test_file), comment="Delete declined"
            )
            interface = MockInterface()
            interface.set_user_inputs(["n"])  # Decline operation
            result = delete_req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is False


class TestCopyRequirement:
    """Test CopyRequirement with real file copying."""

    def test_copy_file(self):
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

            result = req.actually_solve(DEFAULT_CONFIG, mock_interface)

            # Verify copy succeeded
            assert result.accepted
            assert source_file.exists()  # Source should remain
            assert dest_file.exists()  # Destination should exist
            assert source_file.read_text() == test_content
            assert dest_file.read_text() == test_content

    def test_copy_directory_tree(self):
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

            result = req.actually_solve(DEFAULT_CONFIG, mock_interface)

            # Verify directory tree copy
            assert result.accepted
            assert source_dir.exists()  # Original remains
            assert dest_dir.exists()  # Copy created
            assert (dest_dir / "file.txt").read_text() == "Root file"
            assert (dest_dir / "subdir" / "nested.txt").read_text() == "Nested file"

    def test_copy_declined(self):
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
            result = req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is False


class TestMoveRequirement:
    """Test MoveRequirement with real file moves."""

    def test_move_file(self):
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

            result = req.actually_solve(config=DEFAULT_CONFIG, interface=mock_interface)

            # Verify move succeeded
            assert result.accepted
            assert not source_file.exists()  # Source should be gone
            assert dest_file.exists()  # Destination should exist
            assert dest_file.read_text() == test_content

            # Verify paths in result are absolute
            assert Path(str(result.source_path)).is_absolute()
            assert Path(str(result.destination_path)).is_absolute()

    def test_move_directory(self):
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

            result = req.actually_solve(DEFAULT_CONFIG, mock_interface)

            # Verify directory move
            assert result.accepted
            assert not source_dir.exists()
            assert dest_dir.exists()
            assert (dest_dir / "file1.txt").read_text() == "File 1 content"
            assert (dest_dir / "file2.txt").read_text() == "File 2 content"

    def test_move_nonexistent_source(self):
        """Test moving a file that doesn't exist."""
        mock_interface = MockInterface()
        mock_interface.user_inputs.append("y")
        req = MoveRequirement(
            source_path="/nonexistent/source.txt",
            destination_path="/tmp/dest.txt",
            comment="Move missing file",
        )

        result = req.actually_solve(DEFAULT_CONFIG, mock_interface)

        # Should fail gracefully
        assert not result.accepted
        assert result.error is not None

    def test_move_declined(self):
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
            result = req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is False


class TestRequirementErrorHandling:
    """Test error handling and exception scenarios."""

    def test_error_result_creation(self):
        """Test create_error_result method for all requirement types."""
        requirements = [
            CommandRequirement(command="echo test", comment="Test"),
            ReadRequirement(path="/test.txt", metadata_only=False, comment="Test"),
            WriteRequirement(path="/test.txt", is_directory=False, comment="Test"),
            DeleteRequirement(path="/test.txt", comment="Test"),
            CopyRequirement(
                source_path="/src.txt", destination_path="/dst.txt", comment="Test"
            ),
            MoveRequirement(
                source_path="/src.txt", destination_path="/dst.txt", comment="Test"
            ),
        ]

        for req in requirements:
            error_result = req.create_error_result("Test error", accepted=False)
            assert error_result.requirement == req
            assert error_result.accepted is False
            assert error_result.error == "Test error"

    def test_write_encoding_error_handling(self):
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
                result = write_req.solve(DEFAULT_CONFIG, interface)

                # Should handle encoding error
                assert result.accepted is False
                assert "Encoding error" in result.error
                output = interface.get_all_output()
                assert "Found error when writing file" in output

    def test_copy_with_insufficient_space_error(self):
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
                result = copy_req.solve(DEFAULT_CONFIG, interface)

                # Should handle disk space error
                assert result.accepted is False
                assert "No space left on device" in result.error
                output = interface.get_all_output()
                assert "Found error when copying" in output

    def test_real_permission_error_scenarios(self):
        """Test real permission error handling."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            restricted_dir = temp_path / "restricted"
            restricted_dir.mkdir()
            restricted_file = restricted_dir / "file.txt"
            restricted_file.write_text("content")

            # Remove all permissions from directory
            restricted_dir.chmod(0o000)

            try:
                # Try to read file in restricted directory
                read_req = ReadRequirement(
                    path=str(restricted_file),
                    metadata_only=True,
                    comment="Read restricted file",
                )
                interface = MockInterface()

                result = read_req.actually_solve(DEFAULT_CONFIG, interface)

                # Should fail with permission error
                assert not result.accepted
                assert result.error is not None
                assert (
                    "permission denied" in result.error.lower()
                    or "not readable" in result.error.lower()
                )

            finally:
                # Restore permissions for cleanup
                restricted_dir.chmod(0o755)


class TestPathSecurity:
    """Test path security and validation with real filesystem."""

    def test_path_traversal_protection(self):
        """Test that path traversal attempts are handled safely."""
        mock_interface = MockInterface()
        mock_interface.user_inputs.append("y")  # Accept metadata

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            # Create a secret file we shouldn't be able to access via traversal
            secret_dir = temp_path / "secret"
            secret_dir.mkdir()
            secret_file = secret_dir / "confidential.txt"
            secret_file.write_text("SECRET CONTENT")

            # Create a subdirectory to traverse from
            subdir = temp_path / "public" / "subdir"
            subdir.mkdir(parents=True)

            # Try to use path traversal to access the secret file
            traversal_path = str(subdir / ".." / ".." / "secret" / "confidential.txt")

            req = ReadRequirement(
                path=traversal_path,
                metadata_only=True,
                comment="Path traversal attempt",
            )

            result = req.actually_solve(DEFAULT_CONFIG, mock_interface)

            # The path should be resolved to the actual file location
            # Verify the resolved path doesn't contain traversal patterns but does resolve correctly
            expected_resolved = Path(traversal_path).resolve()
            assert str(result.path) == str(expected_resolved)
            assert ".." not in str(result.path)  # No traversal patterns in final path
            assert "secret/confidential.txt" in str(
                result.path
            )  # But does point to right file

    def test_tilde_expansion_security(self):
        """Test that tilde expansion works consistently and securely."""
        # Create tempfile in real home directory to test tilde expansion
        with tempfile.NamedTemporaryFile(
            dir=Path.home(), prefix=".solveig_test_", suffix=".config", delete=False
        ) as temp_file:
            temp_file.write(b"config content")
            temp_file_path = Path(temp_file.name)

        try:
            # Use ~ path that should expand to the tempfile we created
            tilde_path = f"~/{temp_file_path.name}"

            mock_interface = MockInterface()
            mock_interface.user_inputs.append("y")

            req = ReadRequirement(
                path=tilde_path,
                metadata_only=True,
                comment="Tilde expansion test",
            )

            result = req.actually_solve(DEFAULT_CONFIG, mock_interface)

            # Verify tilde expansion worked correctly
            assert result.accepted
            assert str(result.path) == str(temp_file_path.resolve())
            assert "~" not in str(result.path)  # Tilde should be expanded
            assert str(Path.home()) in str(result.path)  # Should contain home path
            assert temp_file_path.name in str(result.path)
        finally:
            # Clean up tempfile
            if temp_file_path.exists():
                temp_file_path.unlink()

    def test_path_expansion_in_requirements(self):
        """Test that path expansion is handled properly in all requirements."""
        # Create tempfile in real home directory to test expansion across requirement types
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

            requirements = [
                ReadRequirement(path=tilde_path, metadata_only=False, comment="Test"),
                WriteRequirement(path=tilde_path, is_directory=False, comment="Test"),
                DeleteRequirement(path=tilde_path, comment="Test"),
            ]

            for req in requirements:
                interface = MockInterface()
                interface.set_user_inputs(
                    ["n", "n"]
                )  # Decline metadata, decline error sending
                result = req.solve(DEFAULT_CONFIG, interface)
                assert result.accepted is False

                # Verify path expansion happened - should contain home path, not ~
                assert "~" not in str(result.path)
                assert str(Path.home()) in str(result.path)
                assert temp_file_path.name in str(result.path)
        finally:
            # Clean up tempfile
            if temp_file_path.exists():
                temp_file_path.unlink()


class TestCompleteWorkflows:
    """Test complete workflows combining multiple file operations."""

    def test_read_modify_write_workflow(self):
        """Test a complete workflow: read file, modify content, write back."""
        mock_interface = MockInterface()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "config.txt"
            config_file.write_text("debug=false\nverbose=true\n")

            # 1. Read the config file
            read_req = ReadRequirement(
                path=str(config_file), metadata_only=False, comment="Read config"
            )
            mock_interface.user_inputs.extend(
                ["y", "y"]  # yes to read, yes to send back
            )

            read_result = read_req.actually_solve(DEFAULT_CONFIG, mock_interface)

            assert read_result.accepted
            original_content = read_result.content

            # 2. Simulate LLM modifying the content
            modified_content = original_content.replace("debug=false", "debug=true")

            # 3. Write the modified content back
            write_req = WriteRequirement(
                path=str(config_file),
                is_directory=False,
                content=modified_content,
                comment="Update config",
            )
            mock_interface.user_inputs.extend(
                [
                    "y",  # yes to write
                ]
            )
            write_result = write_req.actually_solve(DEFAULT_CONFIG, mock_interface)

            assert write_result.accepted

            # 4. Verify the change was actually made
            final_content = config_file.read_text()
            assert "debug=true" in final_content
            assert "verbose=true" in final_content

    def test_backup_and_modify_workflow(self):
        """Test workflow: copy file to backup, then modify original."""
        mock_interface = MockInterface()
        mock_interface.user_inputs.extend(["y", "y"])  # For copy and write operations

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            original_file = temp_path / "important.txt"
            backup_file = temp_path / "important.txt.bak"
            original_content = "Important data that needs backup"

            original_file.write_text(original_content)

            # 1. Create backup copy
            copy_req = CopyRequirement(
                source_path=str(original_file),
                destination_path=str(backup_file),
                comment="Create backup",
            )

            copy_result = copy_req.actually_solve(DEFAULT_CONFIG, mock_interface)

            assert copy_result.accepted
            assert backup_file.exists()
            assert backup_file.read_text() == original_content

            # 2. Modify original
            write_req = WriteRequirement(
                path=str(original_file),
                is_directory=False,
                content="Modified data",
                comment="Modify original",
            )

            write_result = write_req.actually_solve(DEFAULT_CONFIG, mock_interface)

            assert write_result.accepted

            # 3. Verify both files have correct content
            assert original_file.read_text() == "Modified data"
            assert backup_file.read_text() == original_content  # Backup unchanged
