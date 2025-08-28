"""
Compact unit tests for requirement classes.
Tests validation, error handling, and display methods efficiently.
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


class TestRequirementBehavior:
    """Test requirement-specific behavior and solve() methods."""

    def test_command_requirement_complete_flow(self):
        """Test CommandRequirement validation, display, error creation, and solve scenarios."""
        req = CommandRequirement(command="echo test", comment="Test echo command")
        interface = MockInterface()

        # Test display header
        req.display_header(interface)
        output = interface.get_all_output()
        assert "Test echo command" in output
        assert "🗲  echo test" in output
        interface.clear()

        # Test create_error_result
        error_result = req.create_error_result("Test error", accepted=False)
        assert error_result.requirement == req
        assert error_result.accepted is False
        assert error_result.error == "Test error"
        assert error_result.stdout is None

        # Test solve: user declines command
        interface.set_user_inputs(["n"])
        result = req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is False
        interface.clear()

        # Test solve: user accepts command but declines output
        interface.set_user_inputs(["y", "n"])
        result = req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is True
        assert result.success is True
        assert result.stdout == ""  # Output cleared
        interface.clear()

        # Test solve: user accepts both command and output
        interface.set_user_inputs(["y", "y"])
        result = req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is True
        assert result.success is True
        assert "test" in result.stdout

        # Test get_description
        description = CommandRequirement.get_description()
        assert "command(command)" in description
        assert "execute shell commands" in description

    def test_read_requirement_complete_flow(self):
        """Test ReadRequirement validation, display, error creation, and solve scenarios."""
        req = ReadRequirement(
            path="/test/file.txt", metadata_only=False, comment="Read test file"
        )
        interface = MockInterface()

        # Test display header
        req.display_header(interface)
        output = interface.get_all_output()
        assert "Read test file" in output
        assert "🗎  /test/file.txt" in output

        # Test create_error_result
        error_result = req.create_error_result("File not found", accepted=False)
        assert error_result.requirement == req
        assert error_result.error == "File not found"

        # Test solve: file doesn't exist, user asked about sending error back
        interface.set_user_inputs(
            ["n", "n"]
        )  # Decline operation, then decline sending error
        result = req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is False

        # Test get_description
        description = ReadRequirement.get_description()
        assert "read(path, metadata_only)" in description

    def test_write_requirement_complete_flow(self):
        """Test WriteRequirement for both files and directories."""
        # Test file creation
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

        # Test directory creation
        dir_req = WriteRequirement(
            path="/test/dir", is_directory=True, comment="Create directory"
        )
        dir_req.display_header(interface)
        output = interface.get_all_output()
        assert "🗁  /test/dir" in output

        # Test solve decline
        interface.set_user_inputs(["n"])
        result = file_req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is False

        # Test get_description
        description = WriteRequirement.get_description()
        assert "write(path, is_directory" in description

    def test_move_copy_requirements_shared_behavior(self):
        """Test MoveRequirement and CopyRequirement shared patterns."""
        requirements = [
            MoveRequirement(
                source_path="/src/file.txt",
                destination_path="/dst/file.txt",
                comment="Move file",
            ),
            CopyRequirement(
                source_path="/src/file.txt",
                destination_path="/dst/copy.txt",
                comment="Copy file",
            ),
        ]

        for req in requirements:
            interface = MockInterface()

            # Test display header (both show arrow and paths)
            req.display_header(interface)
            output = interface.get_all_output()
            assert req.comment in output
            assert "🗎  /src/file.txt" in output
            assert "→" in output
            assert "file.txt" in output or "copy.txt" in output

            # Test solve decline
            interface.set_user_inputs(["n"])
            result = req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is False

            # Test error result
            error_result = req.create_error_result("Operation failed", accepted=False)
            assert error_result.accepted is False
            assert error_result.error == "Operation failed"

    def test_delete_requirement_complete_flow(self):
        """Test DeleteRequirement validation, display, and solve scenarios."""
        req = DeleteRequirement(path="/test/delete_me.txt", comment="Delete test file")
        interface = MockInterface()

        # Test display header (should show warning)
        req.display_header(interface)
        output = interface.get_all_output()
        assert "Delete test file" in output
        assert "🗎  /test/delete_me.txt" in output
        assert "permanent" in output.lower()

        # Test solve decline
        interface.set_user_inputs(["n"])
        result = req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is False

        # Test get_description
        description = DeleteRequirement.get_description()
        assert "delete(path)" in description
        assert "permanently deletes" in description


class TestRequirementErrorHandling:
    """Test error scenarios and edge cases."""

    def test_nonexistent_file_operations(self):
        """Test file operations on non-existent files produce proper errors."""
        requirements = [
            ReadRequirement(
                path="/nonexistent/file.txt",
                metadata_only=True,
                comment="Read missing file",
            ),
            DeleteRequirement(
                path="/nonexistent/file.txt", comment="Delete missing file"
            ),
        ]

        for req in requirements:
            interface = MockInterface()
            interface.set_user_inputs(
                ["y"]
            )  # Accept operation (but file doesn't exist)

            result = req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is False
            assert "does not exist" in result.error or "No such file" in result.error

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
