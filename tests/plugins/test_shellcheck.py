"""
Tests for the shellcheck plugin.
This tests the shellcheck plugin in isolation from other plugins.
"""

# Config with shellcheck plugin enabled - manually create to avoid copy issues
from dataclasses import replace
from unittest.mock import Mock, patch

from solveig.plugins import hooks
from solveig.plugins.hooks import filter_hooks
from solveig.plugins.hooks.shellcheck import is_obviously_dangerous
from solveig.schema.requirements import CommandRequirement, ReadRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface

SHELLCHECK_CONFIG = replace(DEFAULT_CONFIG, plugins={"shellcheck": {}})


class TestShellcheckPlugin:
    """Test the shellcheck plugin functionality in isolation."""

    def setup_method(self):
        """Ensure shellcheck plugin is properly loaded before each test."""
        interface = MockInterface()
        filter_hooks(interface, SHELLCHECK_CONFIG)

    def test_dangerous_patterns_detection(self):
        """Test that dangerous patterns are correctly identified."""
        dangerous_commands = [
            "rm -rf /",
            "rm -rf /*",
            "mkfs.ext4 /dev/sda1",
            ":(){:|:&};:",  # fork bomb
        ]

        safe_commands = [
            "ls -la",
            "echo hello world",
            "mkdir test_directory",
            "rm file.txt",  # specific file, not rm -rf
        ]

        for cmd in dangerous_commands:
            assert is_obviously_dangerous(cmd), f"Should detect '{cmd}' as dangerous"

        for cmd in safe_commands:
            assert not is_obviously_dangerous(
                cmd
            ), f"Should not detect '{cmd}' as dangerous"

    def test_security_error_message_format(self):
        """Test that dangerous commands produce properly formatted error messages."""
        req = CommandRequirement(
            command="mkfs.ext4 /dev/sda1",
            comment="Test dangerous command error formatting",
        )
        interface = MockInterface()
        interface.set_user_inputs(["n"])  # Decline sending error back to assistant

        result = req.solve(SHELLCHECK_CONFIG, interface)

        assert not result.accepted
        assert "dangerous pattern" in result.error.lower()
        assert (
            "mkfs.ext4" in result.error
        )  # Should mention the specific dangerous command
        assert not result.success

    def test_normal_command_passes_validation(self):
        """Test that normal commands pass shellcheck validation."""
        cmd_req = CommandRequirement(
            command="echo 'hello world'", comment="Test normal command"
        )
        interface = MockInterface()
        interface.set_user_inputs(["n"])  # Decline to run

        # Mock user declining to run the command (we just want to test plugin validation)
        result = cmd_req.solve(SHELLCHECK_CONFIG, interface)

        # Should reach user prompt (not stopped by plugin) and be declined by user
        assert not result.accepted
        assert result.error is None  # No plugin validation error

    @patch("subprocess.run")
    def test_shellcheck_validation_success(self, mock_subprocess):
        """Test successful shellcheck validation."""
        # Mock shellcheck returning success (no issues)
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")

        cmd_req = CommandRequirement(
            command="echo 'properly quoted'", comment="Test successful validation"
        )
        interface = MockInterface()
        interface.set_user_inputs(["n"])  # Decline to run

        result = cmd_req.solve(SHELLCHECK_CONFIG, interface)

        # Should pass validation and reach user prompt
        assert not result.accepted  # Declined by user
        assert result.error is None  # No validation error
        mock_subprocess.assert_called_once()

    @patch("subprocess.run")
    def test_shellcheck_validation_failure(self, mock_subprocess):
        """Test shellcheck finding validation issues."""
        # Mock shellcheck finding issues
        mock_issues = [
            {"level": "error", "message": "Missing quotes around variable"},
            {"level": "warning", "message": "Consider using [[ ]] instead of [ ]"},
        ]
        mock_subprocess.return_value = Mock(
            returncode=1,
            stdout=f"[{mock_issues[0]}, {mock_issues[1]}]".replace("'", '"'),
            stderr="",
        )
        req = CommandRequirement(command="echo $UNQUOTED_VAR", comment="Test")
        interface = MockInterface()
        interface.set_user_inputs(["n"])  # Decline sending error back to assistant

        result = req.solve(SHELLCHECK_CONFIG, interface)

        assert not result.accepted
        assert "shellcheck validation failed" in result.error.lower()
        assert "missing quotes" in result.error.lower()
        mock_subprocess.assert_called_once()

    @patch("subprocess.run")
    def test_shellcheck_not_available(self, mock_subprocess):
        """Test graceful handling when shellcheck command is not found."""
        # Mock shellcheck command not found
        mock_subprocess.side_effect = FileNotFoundError("shellcheck command not found")

        config = SHELLCHECK_CONFIG
        req = CommandRequirement(command="echo test", comment="Test")
        interface = MockInterface()
        interface.set_user_inputs(["n"])  # Decline to run

        result = req.solve(config, interface)

        # Should continue processing gracefully without shellcheck
        assert not result.accepted  # Declined by user
        assert result.error is None  # No plugin error

    @patch("subprocess.run")
    def test_multiple_shellcheck_issues(self, mock_subprocess):
        """Test handling multiple shellcheck warnings and errors."""
        # Mock shellcheck finding multiple issues
        mock_issues = [
            {"level": "error", "message": "Missing quotes around variable"},
            {"level": "warning", "message": "Consider using [[ ]] instead of [ ]"},
            {
                "level": "info",
                "message": "Consider using $(...) instead of legacy backticks",
            },
        ]
        mock_subprocess.return_value = Mock(
            returncode=1,
            stdout=f"[{mock_issues[0]}, {mock_issues[1]}, {mock_issues[2]}]".replace(
                "'", '"'
            ),
            stderr="",
        )

        req = CommandRequirement(
            command="if [ $var = `date` ]; then echo hello; fi",
            comment="Test multiple issues",
        )
        interface = MockInterface()
        interface.set_user_inputs(["n"])  # Decline sending error back to assistant

        result = req.solve(SHELLCHECK_CONFIG, interface)

        assert not result.accepted
        assert "shellcheck validation failed" in result.error.lower()
        # Should mention multiple types of issues
        assert "error" in result.error.lower()
        assert "warning" in result.error.lower()
        mock_subprocess.assert_called_once()


class TestShellcheckPluginIntegration:
    """Test shellcheck plugin integration with Solveig core."""

    def setup_method(self):
        """Ensure shellcheck plugin is properly loaded before each test."""
        interface = MockInterface()
        filter_hooks(interface, SHELLCHECK_CONFIG)

    def test_plugin_registration(self):
        """Test that shellcheck plugin is properly registered."""
        # Should have the shellcheck before hook loaded
        assert len(hooks.HOOKS.before) >= 1
        hook_names = [hook[0].__name__ for hook in hooks.HOOKS.before]
        assert "check_command" in hook_names

    def test_plugin_requirement_filtering(self):
        """Test that shellcheck only runs for CommandRequirement."""

        # CommandRequirement with dangerous pattern should trigger shellcheck
        cmd_req = CommandRequirement(command="rm -rf /", comment="Test")
        interface = MockInterface()
        interface.set_user_inputs(["n"])  # Decline sending error back to assistant
        result = cmd_req.solve(SHELLCHECK_CONFIG, interface)

        # Should be stopped by shellcheck plugin
        assert not result.accepted
        assert "dangerous pattern" in result.error.lower()

        # Test that ReadRequirement doesn't trigger shellcheck
        read_req = ReadRequirement(
            path="/test/nonexistent.txt", metadata_only=True, comment="Test"
        )
        interface2 = MockInterface()
        result = read_req.solve(SHELLCHECK_CONFIG, interface2)

        # Should not be stopped by shellcheck (file validation error is different)
        assert not result.accepted
        assert "does not exist" in result.error.lower()  # File error, not plugin error
