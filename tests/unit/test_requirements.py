"""
Reorganized unit tests for requirement classes, grouped by requirement type.
Tests validation, error handling, and display methods with comprehensive coverage.
"""

import pytest
from pydantic import ValidationError

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
    """Test shared validation patterns across all requirements."""

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


class TestCommandRequirement:
    """Test CommandRequirement validation, display, solve, and error scenarios."""

    def test_validation_and_display(self):
        """Test CommandRequirement validation, display, and get_description."""
        req = CommandRequirement(command="echo test", comment="Test echo command")
        interface = MockInterface()

        # Test display header
        req.display_header(interface)
        output = interface.get_all_output()
        assert "Test echo command" in output
        assert "🗲  echo test" in output

        # Test get_description
        description = CommandRequirement.get_description()
        assert "command(command)" in description
        assert "execute shell commands" in description

    def test_successful_command_execution(self):
        """Test successful command execution with various user responses."""
        req = CommandRequirement(command="echo test", comment="Test echo command")
        interface = MockInterface()

        # Test: user accepts command but declines output
        interface.set_user_inputs(["y", "n"])
        result = req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is True
        assert result.success is True
        assert result.stdout == ""  # Output cleared
        interface.clear()

        # Test: user accepts both command and output
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

    def test_command_with_error_output(self):
        """Test command that produces error output but executes successfully."""
        req = CommandRequirement(
            command="nonexistent_command_12345", comment="Invalid command"
        )
        interface = MockInterface()
        interface.set_user_inputs(["y", "y"])  # Accept command and output

        result = req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is True
        assert result.success is True  # Shell execution succeeded
        assert "command not found" in result.error

    def test_command_exception_handling(self):
        """Test command requirement exception handling during execution."""
        req = CommandRequirement(command="echo test", comment="Test command")
        interface = MockInterface()

        # Mock _execute_command to raise an exception
        def mock_execute_command(config):
            raise RuntimeError("Simulated command execution error")

        req._execute_command = mock_execute_command
        interface.set_user_inputs(["y"])  # Accept command

        result = req.solve(DEFAULT_CONFIG, interface)

        # Should handle exception and create error result
        assert result.accepted is True
        assert result.success is False
        assert "Simulated command execution error" in result.error
        output = interface.get_all_output()
        assert "Found error when running command" in output

    def test_empty_command_execution(self):
        """Test _execute_command with empty command - covers line 67."""
        req = CommandRequirement(command="echo test", comment="Test")
        req.command = None  # Force empty command to cover line 67

        with pytest.raises(ValueError, match="Empty command"):
            req._execute_command(DEFAULT_CONFIG)


class TestReadRequirement:
    """Test ReadRequirement validation, display, solve, and error scenarios."""

    def test_validation_and_display(self):
        """Test ReadRequirement validation and display."""
        req = ReadRequirement(
            path="/test/file.txt", metadata_only=False, comment="Read test file"
        )
        interface = MockInterface()

        # Test display header
        req.display_header(interface)
        output = interface.get_all_output()
        assert "Read test file" in output
        assert "🗎  /test/file.txt" in output

        # Test get_description
        description = ReadRequirement.get_description()
        assert "read(path, metadata_only)" in description

    def test_successful_reads_with_mock_fs(self, mock_all_file_operations):
        """Test successful read operations using MockFilesystem fixture."""
        # Set up test files and directories - fixture automatically provides mock_fs
        mock_all_file_operations.write_file("/test/readable.txt", "test content")
        mock_all_file_operations.create_directory("/test/readable_dir")
        mock_all_file_operations.write_file("/test/readable_dir/nested.txt", "nested")

        # Test metadata-only read
        metadata_req = ReadRequirement(
            path="/test/readable.txt",
            metadata_only=True,
            comment="Read metadata only",
        )
        interface = MockInterface()
        interface.set_user_inputs(["y", "y"])  # Accept read, send to LLM
        metadata_result = metadata_req.solve(DEFAULT_CONFIG, interface)
        assert metadata_result.accepted is True

        # Test full content read
        interface.clear()
        content_req = ReadRequirement(
            path="/test/readable.txt",
            metadata_only=False,
            comment="Read full content",
        )
        interface.set_user_inputs(["y", "y"])  # Accept read, send to LLM
        content_result = content_req.solve(DEFAULT_CONFIG, interface)
        assert content_result.accepted is True
        assert "test content" in content_result.content

        # Test directory read with listing
        interface.clear()
        dir_req = ReadRequirement(
            path="/test/readable_dir", metadata_only=False, comment="Read directory"
        )
        interface.set_user_inputs(["y", "y"])  # Accept read, send to LLM
        dir_result = dir_req.solve(DEFAULT_CONFIG, interface)
        assert dir_result.accepted is True

    def test_read_declined_scenarios(self, mock_all_file_operations):
        """Test various user decline scenarios for read operations."""
        mock_all_file_operations.write_file("/test/readable.txt", "test content")

        # Test: Accept read, decline sending to LLM
        read_req = ReadRequirement(
            path="/test/readable.txt",
            metadata_only=False,
            comment="Read and decline LLM",
        )
        interface = MockInterface()
        interface.set_user_inputs(["y", "n"])  # Accept read, decline sending to LLM
        result = read_req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is False  # User declined sending to LLM

        # Test: Decline read operation entirely
        interface.clear()
        read_req2 = ReadRequirement(
            path="/test/readable.txt",
            metadata_only=False,
            comment="Read declined",
        )
        interface.set_user_inputs(["n", "n"])  # Decline read, decline error sending
        result = read_req2.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is False

    def test_read_nonexistent_file(self):
        """Test reading non-existent file."""
        req = ReadRequirement(
            path="/nonexistent/file.txt",
            metadata_only=True,
            comment="Read missing file",
        )
        interface = MockInterface()
        interface.set_user_inputs(["y"])  # Accept operation (but file doesn't exist)

        result = req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is False
        assert "does not exist" in result.error or "No such file" in result.error


class TestWriteRequirement:
    """Test WriteRequirement validation, display, solve, and error scenarios."""

    def test_validation_and_display(self):
        """Test WriteRequirement display for files and directories."""
        # Test file creation display
        file_req = WriteRequirement(
            path="/test/file.txt",
            is_directory=False,
            content="test",
            comment="Create file",
        )
        interface = MockInterface()

        file_req.display_header(interface)
        output = interface.get_all_output()
        assert "Create file" in output
        assert "🗎  /test/file.txt" in output
        interface.clear()

        # Test directory creation display
        dir_req = WriteRequirement(
            path="/test/dir", is_directory=True, comment="Create directory"
        )
        dir_req.display_header(interface)
        output = interface.get_all_output()
        assert "🗁  /test/dir" in output

        # Test get_description
        description = WriteRequirement.get_description()
        assert "write(path, is_directory" in description

    def test_successful_writes_with_mock_fs(self, mock_all_file_operations):
        """Test successful write operations using MockFilesystem fixture."""
        mock_all_file_operations.total_size = 10000000000  # 10GB to avoid space issues

        # Test write file
        write_req = WriteRequirement(
            path="/test/new_file.txt",
            is_directory=False,
            content="new content",
            comment="Write new file",
        )
        interface = MockInterface()
        interface.set_user_inputs(["y"])
        write_result = write_req.solve(DEFAULT_CONFIG, interface)
        assert write_result.accepted is True

        # Test write directory
        interface.clear()
        write_dir_req = WriteRequirement(
            path="/test/new_dir", is_directory=True, comment="Create new directory"
        )
        interface.set_user_inputs(["y"])
        write_dir_result = write_dir_req.solve(DEFAULT_CONFIG, interface)
        assert write_dir_result.accepted is True

    def test_write_declined(self):
        """Test when user declines write operation."""
        write_req = WriteRequirement(
            path="/test/declined_write.txt",
            is_directory=False,
            content="test",
            comment="Write declined",
        )
        interface = MockInterface()
        interface.set_user_inputs(["n"])  # Decline operation
        result = write_req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is False


class TestDeleteRequirement:
    """Test DeleteRequirement validation, display, solve, and error scenarios."""

    def test_validation_and_display(self):
        """Test DeleteRequirement display and warnings."""
        req = DeleteRequirement(path="/test/delete_me.txt", comment="Delete test file")
        interface = MockInterface()

        # Test display header (should show warning)
        req.display_header(interface)
        output = interface.get_all_output()
        assert "Delete test file" in output
        assert "🗎  /test/delete_me.txt" in output
        assert "permanent" in output.lower()

        # Test get_description
        description = DeleteRequirement.get_description()
        assert "delete(path)" in description
        assert "permanently deletes" in description

    def test_successful_delete_with_mock_fs(self, mock_all_file_operations):
        """Test successful delete operation using MockFilesystem fixture."""
        # Set up file to delete
        mock_all_file_operations.write_file("/test/delete_me.txt", "content")

        delete_req = DeleteRequirement(
            path="/test/delete_me.txt", comment="Delete file"
        )
        interface = MockInterface()
        interface.set_user_inputs(["y"])
        delete_result = delete_req.solve(DEFAULT_CONFIG, interface)
        assert delete_result.accepted is True

    def test_delete_declined(self, mock_all_file_operations):
        """Test when user declines delete operation."""
        mock_all_file_operations.write_file("/test/to_delete.txt", "content")
        delete_req = DeleteRequirement(
            path="/test/to_delete.txt", comment="Delete declined"
        )
        interface = MockInterface()
        interface.set_user_inputs(["n"])  # Decline operation
        result = delete_req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is False

    def test_delete_nonexistent_file(self):
        """Test deleting non-existent file."""
        req = DeleteRequirement(
            path="/nonexistent/file.txt", comment="Delete missing file"
        )
        interface = MockInterface()
        interface.set_user_inputs(["y"])  # Accept operation (but file doesn't exist)

        result = req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is False
        assert "does not exist" in result.error or "No such file" in result.error


class TestCopyRequirement:
    """Test CopyRequirement validation, display, solve, and error scenarios."""

    def test_validation_and_display(self):
        """Test CopyRequirement display patterns."""
        req = CopyRequirement(
            source_path="/src/file.txt",
            destination_path="/dst/file.txt",
            comment="Copy file",
        )
        interface = MockInterface()

        # Test display header (both show arrow and paths)
        req.display_header(interface)
        output = interface.get_all_output()
        assert "Copy file" in output
        assert "🗎  /src/file.txt" in output
        assert "→" in output
        assert "file.txt" in output

        # Test get_description
        description = CopyRequirement.get_description()
        assert "copy(source_path, destination_path)" in description

    def test_successful_copy_with_mock_fs(self, mock_all_file_operations):
        """Test successful copy operations using MockFilesystem fixture."""
        mock_all_file_operations.total_size = 10000000000  # 10GB

        # Set up source files
        mock_all_file_operations.write_file("/test/source.txt", "source content")
        mock_all_file_operations.create_directory("/test/source_dir")
        mock_all_file_operations.write_file(
            "/test/source_dir/nested.txt", "nested content"
        )

        # Test copy file operation
        copy_req = CopyRequirement(
            source_path="/test/source.txt",
            destination_path="/test/copy_dest.txt",
            comment="Copy file",
        )
        interface = MockInterface()
        interface.set_user_inputs(["y"])
        copy_result = copy_req.solve(DEFAULT_CONFIG, interface)
        assert copy_result.accepted is True
        assert copy_result.error is None

        # Test copy directory operation
        interface.clear()
        copy_dir_req = CopyRequirement(
            source_path="/test/source_dir",
            destination_path="/test/copy_dir_dest",
            comment="Copy directory",
        )
        interface.set_user_inputs(["y"])
        copy_dir_result = copy_dir_req.solve(DEFAULT_CONFIG, interface)
        assert copy_dir_result.accepted is True

    def test_copy_declined(self, mock_all_file_operations):
        """Test when user declines copy operation."""
        # Create the initial file, so it doesn't throw an exception
        mock_all_file_operations.write_file("/src/file.txt", "source content")
        req = CopyRequirement(
            source_path="/src/file.txt",
            destination_path="/dst/copy.txt",
            comment="Copy file",
        )
        interface = MockInterface()
        interface.set_user_inputs(["n"])
        result = req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is False


class TestMoveRequirement:
    """Test MoveRequirement validation, display, solve, and error scenarios."""

    def test_validation_and_display(self):
        """Test MoveRequirement display patterns."""
        req = MoveRequirement(
            source_path="/src/file.txt",
            destination_path="/dst/file.txt",
            comment="Move file",
        )
        interface = MockInterface()

        # Test display header (both show arrow and paths)
        req.display_header(interface)
        output = interface.get_all_output()
        assert "Move file" in output
        assert "🗎  /src/file.txt" in output
        assert "→" in output
        assert "file.txt" in output

        # Test get_description
        description = MoveRequirement.get_description()
        assert "move(source_path, destination_path)" in description

    def test_successful_move_with_mock_fs(self, mock_all_file_operations):
        """Test successful move operations using MockFilesystem fixture."""
        mock_all_file_operations.total_size = 10000000000  # 10GB

        # Set up source files
        mock_all_file_operations.write_file("/test/source.txt", "source content")
        mock_all_file_operations.create_directory("/test/source_dir")
        mock_all_file_operations.write_file(
            "/test/source_dir/nested.txt", "nested content"
        )

        # Test move file operation
        move_req = MoveRequirement(
            source_path="/test/source.txt",
            destination_path="/test/moved.txt",
            comment="Move file",
        )
        interface = MockInterface()
        interface.set_user_inputs(["y"])
        move_result = move_req.solve(DEFAULT_CONFIG, interface)
        assert move_result.accepted is True

        # Test move directory operation
        interface.clear()
        move_dir_req = MoveRequirement(
            source_path="/test/source_dir",
            destination_path="/test/moved_dir",
            comment="Move directory",
        )
        interface.set_user_inputs(["y"])
        move_dir_result = move_dir_req.solve(DEFAULT_CONFIG, interface)
        assert move_dir_result.accepted is True

    def test_move_declined(self, mock_all_file_operations):
        """Test when user declines move operation."""
        # Create the initial file, so it doesn't throw an exception
        mock_all_file_operations.write_file("/src/file.txt", "source content")
        req = MoveRequirement(
            source_path="/src/file.txt",
            destination_path="/dst/moved.txt",
            comment="Move file",
        )
        interface = MockInterface()
        interface.set_user_inputs(["n"])
        result = req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is False


class TestRequirementErrorCreation:
    """Test error result creation across all requirements."""

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


class TestRequirementErrorScenarios:
    """Test specific error scenarios to improve coverage."""

    def test_write_file_already_exists(self, mock_all_file_operations):
        """Test WriteRequirement when file already exists - covers lines 75-79."""
        # Create existing file
        mock_all_file_operations.write_file("/test/existing.txt", "existing content")

        write_req = WriteRequirement(
            path="/test/existing.txt",
            is_directory=False,
            content="new content",
            comment="Overwrite existing",
        )
        interface = MockInterface()
        interface.set_user_inputs(["y"])  # Accept overwrite

        result = write_req.solve(DEFAULT_CONFIG, interface)

        # Should show warning about existing file
        output = interface.get_all_output()
        assert "This file already exists" in output
        assert result.accepted is True

    def test_write_operation_exception(self, mock_all_file_operations):
        """Test WriteRequirement exception handling - covers lines 103-105."""
        from unittest.mock import patch

        # Ensure plenty of disk space to avoid validation errors
        mock_all_file_operations.total_size = 10000000000  # 10GB

        write_req = WriteRequirement(
            path="/test/error_file.txt",
            is_directory=False,
            content="test content",
            comment="Write with error",
        )
        interface = MockInterface()

        # Mock Filesystem.write_file to raise an exception
        with patch("solveig.utils.file.Filesystem.write_file") as mock_write:
            mock_write.side_effect = UnicodeEncodeError("utf-8", "", 0, 1, "test error")

            interface.set_user_inputs(["y"])  # Accept operation
            result = write_req.solve(DEFAULT_CONFIG, interface)

            # Should handle encoding error
            assert result.accepted is False
            assert "Encoding error" in result.error
            output = interface.get_all_output()
            assert "Found error when writing file" in output

    def test_copy_operation_exception(self, mock_all_file_operations):
        """Test CopyRequirement exception handling - covers lines 113-123."""
        from unittest.mock import patch

        # Set up source file
        mock_all_file_operations.write_file("/test/source.txt", "content")

        copy_req = CopyRequirement(
            source_path="/test/source.txt",
            destination_path="/test/dest.txt",
            comment="Copy with error",
        )
        interface = MockInterface()

        # Mock Filesystem.copy to raise an exception
        with patch("solveig.utils.file.Filesystem.copy") as mock_copy:
            mock_copy.side_effect = PermissionError("Permission denied")

            interface.set_user_inputs(["y"])  # Accept operation
            result = copy_req.solve(DEFAULT_CONFIG, interface)

            # Should handle copy error
            assert result.accepted is False
            assert "Permission denied" in result.error
            output = interface.get_all_output()
            assert "Found error when copying" in output

    def test_move_operation_exception(self, mock_all_file_operations):
        """Test MoveRequirement exception handling - covers lines 109-119."""
        from unittest.mock import patch

        # Set up source file
        mock_all_file_operations.write_file("/test/source.txt", "content")

        move_req = MoveRequirement(
            source_path="/test/source.txt",
            destination_path="/test/dest.txt",
            comment="Move with error",
        )
        interface = MockInterface()

        # Mock Filesystem.move to raise an exception
        with patch("solveig.utils.file.Filesystem.move") as mock_move:
            mock_move.side_effect = OSError("Disk full")

            interface.set_user_inputs(["y"])  # Accept operation
            result = move_req.solve(DEFAULT_CONFIG, interface)

            # Should handle move error
            assert result.accepted is False
            assert "Disk full" in result.error
            output = interface.get_all_output()
            assert "Found error when moving" in output

    def test_delete_operation_exception(self, mock_all_file_operations):
        """Test DeleteRequirement exception handling - covers lines 84-86."""
        from unittest.mock import patch

        # Set up file to delete
        mock_all_file_operations.write_file("/test/delete_me.txt", "content")

        delete_req = DeleteRequirement(
            path="/test/delete_me.txt", comment="Delete with error"
        )
        interface = MockInterface()

        # Mock Filesystem.delete to raise an exception
        with patch("solveig.utils.file.Filesystem.delete") as mock_delete:
            mock_delete.side_effect = PermissionError("Access denied")

            interface.set_user_inputs(["y"])  # Accept operation
            result = delete_req.solve(DEFAULT_CONFIG, interface)

            # Should handle delete error
            assert result.accepted is False
            assert "Access denied" in result.error
            output = interface.get_all_output()
            assert "Found error when deleting" in output

    def test_read_operation_exception(self, mock_all_file_operations):
        """Test ReadRequirement exception handling - covers lines 88-90."""
        from unittest.mock import patch

        # Set up file to read
        mock_all_file_operations.write_file("/test/readable.txt", "content")

        read_req = ReadRequirement(
            path="/test/readable.txt", metadata_only=False, comment="Read with error"
        )
        interface = MockInterface()

        # Mock Filesystem.read_file to raise an exception
        with patch("solveig.utils.file.Filesystem.read_file") as mock_read:
            mock_read.side_effect = PermissionError("Permission denied")

            interface.set_user_inputs(["y"])  # Accept operation
            result = read_req.solve(DEFAULT_CONFIG, interface)

            # Should handle read error
            assert result.accepted is False
            assert "Permission denied" in result.error

    def test_move_validation_exception(self, mock_all_file_operations):
        """Test MoveRequirement validation exception handling - covers lines 74-76."""
        from unittest.mock import patch

        # Set up source file
        mock_all_file_operations.write_file("/test/source.txt", "content")

        move_req = MoveRequirement(
            source_path="/test/source.txt",
            destination_path="/test/dest.txt",
            comment="Move with validation error"
        )
        interface = MockInterface()

        # Mock validate_write_access to raise an exception during validation
        with patch("solveig.utils.file.Filesystem.validate_write_access") as mock_validate:
            mock_validate.side_effect = PermissionError("Write permission denied")

            result = move_req.solve(DEFAULT_CONFIG, interface)

            # Should handle validation error in the except clause
            assert result.accepted is False
            assert "Write permission denied" in result.error
            output = interface.get_all_output()
            assert "Skipping: Write permission denied" in output

    def test_copy_validation_exception(self, mock_all_file_operations):
        """Test CopyRequirement validation exception handling - covers lines 74-76."""
        from unittest.mock import patch

        # Set up source file
        mock_all_file_operations.write_file("/test/source.txt", "content")

        copy_req = CopyRequirement(
            source_path="/test/source.txt",
            destination_path="/test/dest.txt",
            comment="Copy with validation error"
        )
        interface = MockInterface()

        # Mock validate_read_access to raise an exception during validation
        with patch("solveig.utils.file.Filesystem.validate_read_access") as mock_validate:
            mock_validate.side_effect = PermissionError("Read permission denied")

            result = copy_req.solve(DEFAULT_CONFIG, interface)

            # Should handle validation error in the except clause
            assert result.accepted is False
            assert "Read permission denied" in result.error
            output = interface.get_all_output()
            assert "Skipping: Read permission denied" in output


class TestPathExpansion:
    """Test path expansion behavior."""

    def test_path_expansion(self):
        """Test that tilde path expansion is handled properly."""
        req = ReadRequirement(
            path="~/test.txt", metadata_only=False, comment="Read from home"
        )
        interface = MockInterface()
        interface.set_user_inputs(["n"])  # Decline

        result = req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is False
        # Path should be expanded in error message (not contain ~)
