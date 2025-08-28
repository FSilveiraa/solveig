"""
Unit tests for requirement classes.
Tests validation, error handling, and display methods.
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


class TestCommandRequirement:
    """Test CommandRequirement validation and methods."""

    def test_command_validation_success(self):
        """Test successful command validation."""
        req = CommandRequirement(command="ls -la", comment="List files")
        assert req.command == "ls -la"
        assert req.comment == "List files"

    def test_command_validation_empty_string(self):
        """Test validation fails for empty command string."""
        with pytest.raises(ValidationError) as exc_info:
            CommandRequirement(command="", comment="Empty command")
        
        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("command",)
        assert "Empty command" in str(errors[0]["msg"])

    def test_command_validation_whitespace_only(self):
        """Test validation fails for whitespace-only command."""
        with pytest.raises(ValidationError) as exc_info:
            CommandRequirement(command="   \n\t  ", comment="Whitespace command")
        
        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("command",)
        assert "Empty command" in str(errors[0]["msg"])

    def test_command_validation_none(self):
        """Test validation fails for None command."""
        with pytest.raises(ValidationError) as exc_info:
            CommandRequirement(command=None, comment="None command")
        
        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("command",)

    def test_command_strips_whitespace(self):
        """Test command is stripped of leading/trailing whitespace."""
        req = CommandRequirement(command="  ls -la  ", comment="Test")
        assert req.command == "ls -la"

    def test_display_header(self):
        """Test display_header method."""
        interface = MockInterface()
        req = CommandRequirement(command="ls -la", comment="List directory contents")
        
        req.display_header(interface)
        
        output = interface.get_all_output()
        assert "List directory contents" in output
        assert "🗲  ls -la" in output

    def test_create_error_result(self):
        """Test create_error_result method."""
        req = CommandRequirement(command="ls -la", comment="Test command")
        result = req.create_error_result("Test error message", accepted=False)
        
        assert result.requirement == req
        assert result.command == "ls -la"
        assert result.accepted is False
        assert result.success is False
        assert result.error == "Test error message"
        assert result.stdout is None

    def test_solve_command_declined(self):
        """Test command requirement when user declines to run."""
        req = CommandRequirement(command="ls -la", comment="List files")
        interface = MockInterface()
        interface.set_user_inputs(["n"])  # Decline to run
        
        result = req.solve(DEFAULT_CONFIG, interface)
        
        assert result.accepted is False
        assert result.command == "ls -la"
        assert result.requirement == req

    def test_solve_command_accepted_but_output_declined(self):
        """Test command accepted but user declines to send output."""
        req = CommandRequirement(command="echo test", comment="Test echo")
        interface = MockInterface()
        interface.set_user_inputs(["y", "n"])  # Accept command, decline output
        
        result = req.solve(DEFAULT_CONFIG, interface)
        
        assert result.accepted is True
        assert result.success is True
        assert result.stdout == ""  # Output cleared because declined
        assert result.command == "echo test"

    def test_solve_command_fully_accepted(self):
        """Test command fully accepted with output."""
        req = CommandRequirement(command="echo hello", comment="Test echo")
        interface = MockInterface()
        interface.set_user_inputs(["y", "y"])  # Accept command and output
        
        result = req.solve(DEFAULT_CONFIG, interface)
        
        assert result.accepted is True
        assert result.success is True
        assert "hello" in result.stdout
        assert result.command == "echo hello"

    def test_get_description(self):
        """Test get_description class method."""
        description = CommandRequirement.get_description()
        assert "command(command)" in description
        assert "execute shell commands" in description


class TestReadRequirement:
    """Test ReadRequirement validation and methods."""

    def test_path_validation_success(self):
        """Test successful path validation."""
        req = ReadRequirement(path="/home/user/file.txt", metadata_only=False, comment="Read file")
        assert req.path == "/home/user/file.txt"
        assert req.metadata_only is False

    def test_path_validation_empty_string(self):
        """Test validation fails for empty path."""
        with pytest.raises(ValidationError) as exc_info:
            ReadRequirement(path="", metadata_only=False, comment="Empty path")
        
        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("path",)
        assert "Empty path" in str(errors[0]["msg"])

    def test_path_validation_whitespace_only(self):
        """Test validation fails for whitespace-only path."""
        with pytest.raises(ValidationError) as exc_info:
            ReadRequirement(path="   \t\n   ", metadata_only=False, comment="Whitespace path")
        
        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("path",)

    def test_path_strips_whitespace(self):
        """Test path is stripped of leading/trailing whitespace."""
        req = ReadRequirement(path="  /home/user/file.txt  ", metadata_only=False, comment="Test")
        assert req.path == "/home/user/file.txt"

    def test_display_header(self):
        """Test display_header method."""
        interface = MockInterface()
        req = ReadRequirement(path="/home/user/test.txt", metadata_only=False, comment="Read test file")
        
        req.display_header(interface)
        
        output = interface.get_all_output()
        assert "Read test file" in output
        assert "🗎  /home/user/test.txt" in output

    def test_create_error_result(self):
        """Test create_error_result method."""
        req = ReadRequirement(path="/home/user/test.txt", metadata_only=False, comment="Test read")
        result = req.create_error_result("Test error message", accepted=False)
        
        assert result.requirement == req
        assert result.accepted is False
        assert result.error == "Test error message"

    def test_get_description(self):
        """Test get_description class method."""
        description = ReadRequirement.get_description()
        assert "read(path, metadata_only)" in description
        assert "metadata only" in description


class TestWriteRequirement:
    """Test WriteRequirement validation and methods."""

    def test_file_creation_validation(self):
        """Test validation for file creation."""
        req = WriteRequirement(path="/tmp/test.txt", is_directory=False, content="test", comment="Create file")
        assert req.path == "/tmp/test.txt"
        assert req.is_directory is False
        assert req.content == "test"

    def test_directory_creation_validation(self):
        """Test validation for directory creation."""
        req = WriteRequirement(path="/tmp/testdir", is_directory=True, comment="Create directory")
        assert req.path == "/tmp/testdir"
        assert req.is_directory is True
        assert req.content is None

    def test_path_validation_empty(self):
        """Test validation fails for empty path."""
        with pytest.raises(ValidationError) as exc_info:
            WriteRequirement(path="", is_directory=False, comment="Empty path")
        
        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("path",)

    def test_display_header_file(self):
        """Test display_header for file creation."""
        interface = MockInterface()
        req = WriteRequirement(path="/tmp/test.txt", is_directory=False, content="test", comment="Create test file")
        
        req.display_header(interface)
        
        output = interface.get_all_output()
        assert "Create test file" in output
        assert "🗎  /tmp/test.txt" in output

    def test_display_header_directory(self):
        """Test display_header for directory creation."""
        interface = MockInterface()
        req = WriteRequirement(path="/tmp/testdir", is_directory=True, comment="Create test directory")
        
        req.display_header(interface)
        
        output = interface.get_all_output()
        assert "Create test directory" in output
        assert "🗁  /tmp/testdir" in output

    def test_create_error_result(self):
        """Test create_error_result method."""
        req = WriteRequirement(path="/tmp/test.txt", is_directory=False, content="test", comment="Test write")
        result = req.create_error_result("Test error message", accepted=False)
        
        assert result.requirement == req
        assert result.accepted is False
        assert result.error == "Test error message"

    def test_get_description(self):
        """Test get_description class method."""
        description = WriteRequirement.get_description()
        assert "write(path, is_directory" in description
        assert "creates a new file or directory" in description


class TestMoveRequirement:
    """Test MoveRequirement validation and methods."""

    def test_path_validation_success(self):
        """Test successful path validation."""
        req = MoveRequirement(
            source_path="/home/user/file.txt",
            destination_path="/home/user/moved_file.txt", 
            comment="Move file"
        )
        assert req.source_path == "/home/user/file.txt"
        assert req.destination_path == "/home/user/moved_file.txt"

    def test_source_path_validation_empty(self):
        """Test validation fails for empty source path."""
        with pytest.raises(ValidationError) as exc_info:
            MoveRequirement(source_path="", destination_path="/dest", comment="Empty source")
        
        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("source_path",)

    def test_destination_path_validation_empty(self):
        """Test validation fails for empty destination path."""
        with pytest.raises(ValidationError) as exc_info:
            MoveRequirement(source_path="/src", destination_path="", comment="Empty dest")
        
        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("destination_path",)

    def test_display_header(self):
        """Test display_header method."""
        interface = MockInterface()
        req = MoveRequirement(
            source_path="/home/user/file.txt",
            destination_path="/home/user/moved.txt", 
            comment="Move test file"
        )
        
        req.display_header(interface)
        
        output = interface.get_all_output()
        assert "Move test file" in output
        assert "🗎  /home/user/file.txt" in output
        assert "→" in output
        assert "/home/user/moved.txt" in output

    def test_create_error_result(self):
        """Test create_error_result method."""
        req = MoveRequirement(
            source_path="/home/user/file.txt",
            destination_path="/home/user/moved.txt", 
            comment="Test move"
        )
        result = req.create_error_result("Test error message", accepted=False)
        
        assert result.requirement == req
        assert result.accepted is False
        assert result.error == "Test error message"

    def test_get_description(self):
        """Test get_description class method."""
        description = MoveRequirement.get_description()
        assert "move(source_path, destination_path)" in description
        assert "moves a file or directory" in description


class TestCopyRequirement:
    """Test CopyRequirement validation and methods."""

    def test_path_validation_success(self):
        """Test successful path validation."""
        req = CopyRequirement(
            source_path="/home/user/file.txt",
            destination_path="/home/user/copy_file.txt", 
            comment="Copy file"
        )
        assert req.source_path == "/home/user/file.txt"
        assert req.destination_path == "/home/user/copy_file.txt"

    def test_source_path_validation_empty(self):
        """Test validation fails for empty source path."""
        with pytest.raises(ValidationError) as exc_info:
            CopyRequirement(source_path="", destination_path="/dest", comment="Empty source")
        
        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("source_path",)

    def test_destination_path_validation_empty(self):
        """Test validation fails for empty destination path."""
        with pytest.raises(ValidationError) as exc_info:
            CopyRequirement(source_path="/src", destination_path="", comment="Empty dest")
        
        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("destination_path",)

    def test_display_header(self):
        """Test display_header method."""
        interface = MockInterface()
        req = CopyRequirement(
            source_path="/home/user/file.txt",
            destination_path="/home/user/copy.txt", 
            comment="Copy test file"
        )
        
        req.display_header(interface)
        
        output = interface.get_all_output()
        assert "Copy test file" in output
        assert "🗎  /home/user/file.txt" in output
        assert "→" in output
        assert "/home/user/copy.txt" in output

    def test_create_error_result(self):
        """Test create_error_result method."""
        req = CopyRequirement(
            source_path="/home/user/file.txt",
            destination_path="/home/user/copy.txt", 
            comment="Test copy"
        )
        result = req.create_error_result("Test error message", accepted=False)
        
        assert result.requirement == req
        assert result.accepted is False
        assert result.error == "Test error message"

    def test_get_description(self):
        """Test get_description class method."""
        description = CopyRequirement.get_description()
        assert "copy(source_path, destination_path)" in description
        assert "copies a file or directory" in description


class TestDeleteRequirement:
    """Test DeleteRequirement validation and methods."""

    def test_path_validation_success(self):
        """Test successful path validation."""
        req = DeleteRequirement(path="/tmp/delete_me.txt", comment="Delete file")
        assert req.path == "/tmp/delete_me.txt"

    def test_path_validation_empty(self):
        """Test validation fails for empty path."""
        with pytest.raises(ValidationError) as exc_info:
            DeleteRequirement(path="", comment="Empty path")
        
        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("path",)

    def test_display_header(self):
        """Test display_header method."""
        interface = MockInterface()
        req = DeleteRequirement(path="/tmp/delete_me.txt", comment="Delete test file")
        
        req.display_header(interface)
        
        output = interface.get_all_output()
        assert "Delete test file" in output
        assert "🗎  /tmp/delete_me.txt" in output
        assert "permanent" in output.lower()

    def test_create_error_result(self):
        """Test create_error_result method."""
        req = DeleteRequirement(path="/tmp/delete_me.txt", comment="Test delete")
        result = req.create_error_result("Test error message", accepted=False)
        
        assert result.requirement == req
        assert result.accepted is False
        assert result.error == "Test error message"

    def test_get_description(self):
        """Test get_description class method."""
        description = DeleteRequirement.get_description()
        assert "delete(path)" in description
        assert "permanently deletes" in description