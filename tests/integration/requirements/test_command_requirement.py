"""Integration tests for CommandRequirement."""

import pytest
from pydantic import ValidationError

from solveig.config import SolveigConfig
from solveig.schema.requirements import CommandRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface

# Mark all tests in this module to skip file mocking
pytestmark = pytest.mark.no_file_mocking


class TestCommandValidation:
    """Test CommandRequirement validation patterns."""

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


class TestCommandDisplay:
    """Test CommandRequirement display methods."""

    @pytest.mark.anyio
    async def test_command_requirement_display(self):
        """Test CommandRequirement display and description."""
        req = CommandRequirement(command="echo test", comment="Test echo command")
        interface = MockInterface()

        # Test display header
        await req.display_header(interface)
        output = interface.get_all_output()
        assert "Test echo command" in output
        assert "echo test" in output  # Command should be shown in text block

        # Test get_description
        description = CommandRequirement.get_description()
        assert "command(command)" in description
        assert "execute shell commands" in description


class TestCommandExecution:
    """Test CommandRequirement execution with real subprocess calls."""

    @pytest.mark.anyio
    async def test_auto_execute_matching_pattern(self, mock_subprocess):
        """Test command auto-execution when pattern matches."""
        # Configure mock subprocess for successful execution
        mock_subprocess.communicate.side_effect = None
        mock_subprocess.communicate.return_value = (b"test output\n", b"")

        # Create config with auto-execute patterns
        config = SolveigConfig(auto_execute_commands=["^ls\\s*$", "^pwd\\s*$"])
        req = CommandRequirement(command="ls", comment="Test ls command")
        interface = MockInterface()

        # Auto-execute still asks about sending output
        interface.set_user_inputs(["y"])

        result = await req.solve(config, interface)

        # Verify result
        assert result.accepted is True
        assert result.success is True
        assert result.command == "ls"
        assert result.stdout == "test output"

        # Verify auto-execute message was displayed
        output = interface.get_all_output()
        assert "Auto-executing ls" in output
        # Should NOT ask about running command
        assert "Allow running command?" not in output

        # Verify communicate was called correctly
        mock_subprocess.communicate.assert_called_once_with()

    @pytest.mark.anyio
    async def test_auto_execute_non_matching_pattern(self, mock_subprocess):
        """Test normal flow when command doesn't match auto-execute patterns."""
        # Create config with auto-execute patterns
        config = SolveigConfig(auto_execute_commands=["^ls\\s*$", "^pwd\\s*$"])
        req = CommandRequirement(command="echo test", comment="Test echo command")
        interface = MockInterface()

        # Set user to decline the command
        interface.set_user_inputs(["n"])

        result = await req.solve(config, interface)

        # Verify normal prompt flow occurred
        assert result.accepted is False
        assert "Allow running command?" in interface.get_all_questions()
        assert "Auto-executing" not in interface.get_all_output()

        # Verify communicate was NOT called since user declined
        mock_subprocess.communicate.assert_not_called()

    @pytest.mark.anyio
    async def test_auto_execute_with_flags(self, mock_subprocess):
        """Test auto-execute with commands that have flags."""
        # Configure mock subprocess for successful execution
        mock_subprocess.communicate.side_effect = None
        mock_subprocess.communicate.return_value = (b"file list\n", b"")

        # Pattern allows ls with -l and/or -a flags
        config = SolveigConfig(auto_execute_commands=["^ls\\s+-[la]+\\s*$"])

        test_cases = [
            ("ls -l", True),
            ("ls -a", True),
            ("ls -la", True),
            ("ls -al", True),
            ("ls -xyz", False),  # Should not match
            ("ls", False),  # Should not match (no flags)
        ]

        for command, should_auto_execute in test_cases:
            mock_subprocess.reset_mock()  # Reset call count for each test
            req = CommandRequirement(command=command, comment=f"Test {command}")
            interface = MockInterface()

            if should_auto_execute:
                # Auto-execute still asks about sending output
                interface.set_user_inputs(["y"])
            else:
                # Normal flow - decline command execution
                interface.set_user_inputs(["n"])

            result = await req.solve(config, interface)
            output = interface.get_all_output()

            if should_auto_execute:
                assert result.accepted is True
                assert result.success is True
                assert f"Auto-executing {command}" in output
                assert "Allow running command?" not in interface.get_all_questions()
                mock_subprocess.communicate.assert_called_once_with()
            else:
                assert "Allow running command?" in interface.get_all_questions()
                assert "Auto-executing" not in output
                mock_subprocess.communicate.assert_not_called()

    @pytest.mark.anyio
    async def test_auto_execute_empty_patterns(self, mock_subprocess):
        """Test that empty auto_execute_commands list works normally."""
        config = SolveigConfig(auto_execute_commands=[])
        req = CommandRequirement(command="ls", comment="Test ls command")
        interface = MockInterface()

        interface.set_user_inputs(["n"])

        result = await req.solve(config, interface)

        # Should follow normal prompt flow
        assert result.accepted is False
        assert "Allow running command?" in interface.get_all_questions()
        assert "Auto-executing" not in interface.get_all_output()

        # Verify subprocess was NOT called since user declined
        mock_subprocess.assert_not_called()

    @pytest.mark.anyio
    async def test_successful_command_execution(self, mock_subprocess):
        """Test successful command execution."""
        # Configure mock subprocess for successful execution
        mock_subprocess.communicate.side_effect = None
        mock_subprocess.communicate.return_value = (b"test\n", b"")

        req = CommandRequirement(command="echo test", comment="Test echo command")
        interface = MockInterface()

        # Test: user accepts command and output
        interface.set_user_inputs(["y", "y"])
        result = await req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is True
        assert result.success is True
        assert "test" in result.stdout

        # Verify communicate was called correctly (no arguments)
        mock_subprocess.communicate.assert_called_once_with()

    @pytest.mark.anyio
    async def test_command_declined(self, mock_subprocess):
        """Test when user declines command execution."""
        req = CommandRequirement(command="echo test", comment="Test echo command")
        interface = MockInterface()

        interface.set_user_inputs(["n"])
        result = await req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is False

        # Verify communicate was NOT called since user declined
        mock_subprocess.communicate.assert_not_called()

    @pytest.mark.anyio
    async def test_command_with_error_output(self, mock_subprocess):
        """Test command that produces error output."""
        # Configure mock subprocess to return error
        mock_subprocess.communicate.side_effect = None
        mock_subprocess.communicate.return_value = (b"", b"test error\n")

        req = CommandRequirement(
            command="failing_command",
            comment="Command with error",
        )
        interface = MockInterface()
        interface.set_user_inputs(["y", "y"])  # Accept command and output

        result = await req.solve(DEFAULT_CONFIG, interface)
        assert result.accepted is True
        assert result.success is True  # Shell execution succeeded (ran the command)
        assert "test error" in result.error  # Should have specific error content

        mock_subprocess.communicate.assert_called_once_with()

    @pytest.mark.anyio
    async def test_empty_command_execution(self, mock_subprocess):
        """Test _execute_command with empty command."""
        req = CommandRequirement(command="echo test", comment="Test")
        req.command = None  # Force empty command

        with pytest.raises(ValueError, match="Empty command"):
            await req._execute_command(DEFAULT_CONFIG)

        # Verify communicate was NOT called for empty command
        mock_subprocess.communicate.assert_not_called()


class TestCommandSerialization:
    """Test CommandRequirement and CommandResult serialization."""

    @pytest.mark.anyio
    async def test_command_requirement_and_result_serialization(self, mock_subprocess):
        """Test that CommandRequirement and CommandResult serialize properly with actual output data."""
        # Configure mock subprocess to return actual output
        mock_subprocess.communicate.side_effect = None
        mock_subprocess.communicate.return_value = (b"Hello World\nLine 2\n", b"warning message\n")

        # Create requirement
        req = CommandRequirement(command="echo 'Hello World'", comment="Test serialization")
        interface = MockInterface()
        interface.set_user_inputs(["y", "y"])  # Accept command and output

        # Execute and get result
        result = await req.solve(DEFAULT_CONFIG, interface)

        # Test requirement serialization
        req_json = req.model_dump()
        assert req_json["title"] == "command"
        assert req_json["command"] == "echo 'Hello World'"
        assert req_json["comment"] == "Test serialization"

        # Test result serialization
        result_json = result.model_dump()
        assert result_json["accepted"] is True
        assert result_json["success"] is True
        assert result_json["command"] == "echo 'Hello World'"
        assert result_json["stdout"] == "Hello World\nLine 2"  # Actual output must be present
        assert result_json["error"] == "warning message"  # Error output must be present

        # Verify the result has a requirement field that is removed from the JSON
        assert result.requirement.command == "echo 'Hello World'"
        assert "requirement" not in result_json

    @pytest.mark.anyio
    async def test_command_result_error_serialization(self, mock_subprocess):
        """Test CommandResult serialization when command fails."""
        # Configure mock subprocess to simulate command failure
        mock_subprocess.communicate.side_effect = None
        mock_subprocess.communicate.return_value = (b"", b"command not found\n")

        req = CommandRequirement(command="nonexistent_command", comment="Test error")
        interface = MockInterface()
        interface.set_user_inputs(["y", "y"])  # Accept command and output

        result = await req.solve(DEFAULT_CONFIG, interface)

        # Test error result serialization
        assert result.model_dump() == {
            "accepted": True,
            "error": "command not found",
            "command": "nonexistent_command",
            "success": True,   # Shell executed (even if command failed)
            "stdout": "",
        }

    def test_command_declined_result_serialization(self):
        """Test CommandResult serialization when user declines."""
        req = CommandRequirement(command="rm -rf /", comment="Dangerous command")

        # Create declined result
        declined_result = req.create_error_result("User declined", accepted=False)

        # Test serialization of declined result
        assert declined_result.model_dump() == {
            "accepted": False,
            "error": "User declined",
            "command": "rm -rf /",
            "success": False,
            "stdout": None,
        }


class TestCommandErrorHandling:
    """Test CommandRequirement error handling."""

    def test_error_result_creation(self):
        """Test create_error_result method for CommandRequirement."""
        req = CommandRequirement(command="echo test", comment="Test")
        error_result = req.create_error_result("Test error", accepted=False)
        assert error_result.requirement == req
        assert error_result.accepted is False
        assert error_result.error == "Test error"
