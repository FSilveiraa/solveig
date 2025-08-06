"""
Tests for the shellcheck plugin.
This tests the shellcheck plugin in isolation from other plugins.
"""

from unittest.mock import Mock, patch

import pytest

from solveig.plugins import hooks
from solveig.plugins.exceptions import SecurityError, ValidationError
from solveig.plugins.hooks.shellcheck import (
    check_command,
    is_obviously_dangerous,
)
from solveig.schema.requirement import CommandRequirement
from tests.test_utils import DEFAULT_CONFIG


class TestShellcheckPlugin:
    """Test the shellcheck plugin functionality in isolation."""

    # No setup needed - plugins are auto-loaded when importing schema

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

    def test_security_error_on_dangerous_command(self):
        """Test that dangerous commands raise SecurityError."""
        config = DEFAULT_CONFIG
        req = CommandRequirement(comment="Test dangerous command", command="rm -rf /")

        result = req.solve(config)

        assert not result.accepted
        assert "dangerous pattern" in result.error.lower()
        assert not result.success

    def test_normal_command_passes_validation(self):
        """Test that normal commands pass shellcheck validation."""
        config = DEFAULT_CONFIG
        req = CommandRequirement(
            comment="Test normal command", command="echo 'hello world'"
        )

        # Mock user declining to run the command (we just want to test plugin validation)
        with patch("solveig.utils.misc.ask_yes", return_value=False):
            result = req.solve(config)

        # Should reach user prompt (not stopped by plugin) and be declined by user
        assert not result.accepted
        assert result.error is None  # No plugin validation error

    @patch("subprocess.run")
    def test_shellcheck_validation_success(self, mock_subprocess):
        """Test successful shellcheck validation."""
        # Mock shellcheck returning success (no issues)
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")

        config = DEFAULT_CONFIG
        req = CommandRequirement(comment="Test", command="echo test")

        with patch("solveig.utils.misc.ask_yes", return_value=False):
            result = req.solve(config)

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

        config = DEFAULT_CONFIG
        req = CommandRequirement(comment="Test", command="echo $UNQUOTED_VAR")

        result = req.solve(config)

        assert not result.accepted
        assert "shellcheck validation failed" in result.error.lower()
        assert "missing quotes" in result.error.lower()
        mock_subprocess.assert_called_once()

    @patch("subprocess.run")
    def test_shellcheck_not_available(self, mock_subprocess):
        """Test graceful handling when shellcheck command is not found."""
        # Mock shellcheck command not found
        mock_subprocess.side_effect = FileNotFoundError("shellcheck command not found")

        config = DEFAULT_CONFIG
        req = CommandRequirement(comment="Test", command="echo test")

        with patch("solveig.utils.misc.ask_yes", return_value=False):
            result = req.solve(config)

        # Should continue processing gracefully without shellcheck
        assert not result.accepted  # Declined by user
        assert result.error is None  # No plugin error

    def test_direct_hook_call_dangerous_command(self):
        """Test calling the shellcheck hook function directly with dangerous command."""
        config = DEFAULT_CONFIG
        req = CommandRequirement(comment="Direct test", command="rm -rf /important")

        with pytest.raises(SecurityError, match="dangerous pattern"):
            check_command(config, req)

    def test_direct_hook_call_safe_command(self):
        """Test calling the shellcheck hook function directly with safe command."""
        config = DEFAULT_CONFIG
        req = CommandRequirement(comment="Direct test", command="ls -la")

        with patch("subprocess.run") as mock_subprocess:
            mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")

            # Should not raise exception for safe command
            check_command(config, req)
            mock_subprocess.assert_called_once()

    @patch("subprocess.run")
    def test_shellcheck_json_parsing_error(self, mock_subprocess):
        """Test handling of malformed JSON from shellcheck."""
        # Mock shellcheck returning invalid JSON
        mock_subprocess.return_value = Mock(
            returncode=1, stdout="invalid json output", stderr=""
        )

        config = DEFAULT_CONFIG
        req = CommandRequirement(comment="Test", command="bad command")

        # Should handle JSON parsing error gracefully and not crash
        with pytest.raises(ValidationError):
            check_command(config, req)


class TestShellcheckPluginIntegration:
    """Test shellcheck plugin integration with Solveig core."""

    # No setup needed - plugins are auto-loaded when importing schema

    def test_plugin_registration(self):
        """Test that shellcheck plugin is properly registered."""
        # Should have the shellcheck before hook loaded
        assert len(hooks.HOOKS.before) >= 1
        hook_names = [hook[0].__name__ for hook in hooks.HOOKS.before]
        assert "check_command" in hook_names

    def test_plugin_requirement_filtering(self):
        """Test that shellcheck only runs for CommandRequirement."""
        config = DEFAULT_CONFIG

        # CommandRequirement with dangerous pattern should trigger shellcheck
        cmd_req = CommandRequirement(comment="Test", command="rm -rf /")
        result = cmd_req.solve(config)

        # Should be stopped by shellcheck plugin
        assert not result.accepted
        assert "dangerous pattern" in result.error.lower()

        # Test that ReadRequirement doesn't trigger shellcheck
        from solveig.schema.requirement import ReadRequirement

        read_req = ReadRequirement(
            comment="Test", path="/test/file", only_read_metadata=True
        )

        with (
            patch("solveig.utils.misc.ask_yes", return_value=False),
            patch(
                "solveig.utils.file.validate_read_access",
                side_effect=FileNotFoundError("File not found"),
            ),
        ):
            result = read_req.solve(config)

        # Should not be stopped by shellcheck (file validation error is different)
        assert not result.accepted
        assert "file not found" in result.error.lower()  # File error, not plugin error
