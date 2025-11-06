"""
Tests for the shellcheck plugin.
This tests the shellcheck plugin in isolation from other plugins.
"""

# Config with shellcheck plugin enabled - manually create to avoid copy issues
from dataclasses import replace

import pytest

from solveig.plugins import hooks, initialize_plugins
from solveig.plugins.hooks.shellcheck import is_obviously_dangerous
from solveig.schema.requirements import CommandRequirement, ReadRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface

SHELLCHECK_CONFIG = replace(DEFAULT_CONFIG, plugins={"shellcheck": {}})


class TestShellcheckPlugin:
    """Test the shellcheck plugin functionality in isolation."""

    @pytest.fixture(autouse=True)
    async def setup_shellcheck(self):
        """Load shellcheck plugin for each test."""
        self.interface = MockInterface()
        await initialize_plugins(config=SHELLCHECK_CONFIG, interface=self.interface)

    @pytest.mark.anyio
    async def test_dangerous_patterns_detection(self):
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
            assert not is_obviously_dangerous(cmd), (
                f"Should not detect '{cmd}' as dangerous"
            )

    @pytest.mark.no_subprocess_mocking
    @pytest.mark.anyio
    async def test_security_error_message_format(self):
        """Test that dangerous commands produce properly formatted error messages."""
        req = CommandRequirement(
            command="mkfs.ext4 /__non-existent-path__/sdx1",
            comment="Test dangerous command error formatting",
        )
        self.interface.set_user_inputs(["n"])  # Decline sending error back to assistant

        result = await req.solve(SHELLCHECK_CONFIG, self.interface)

        assert not result.accepted
        assert "dangerous pattern" in result.error.lower()
        assert (
            "mkfs.ext4" in result.error
        )  # Should mention the specific dangerous command
        assert not result.success

    @pytest.mark.no_subprocess_mocking
    @pytest.mark.anyio
    async def test_normal_command_passes_validation(self):
        """
        Test that normal commands pass shellcheck validation.
        Note that this test runs the actual shellcheck command on the user's shell, it doesn't
        just get rid of the mock's exception, and will likely fail if shellcheck isn't installed
        """
        cmd_req = CommandRequirement(
            command="echo 'hello world'", comment="Test normal command"
        )
        self.interface.set_user_inputs(["n"])  # Decline to run

        # Mock user declining to run the command (we just want to test plugin validation)
        result = await cmd_req.solve(SHELLCHECK_CONFIG, self.interface)

        # Should reach user prompt (not stopped by plugin) and be declined by user
        assert not result.accepted
        assert result.error is None  # No plugin validation error

    @pytest.mark.no_subprocess_mocking
    @pytest.mark.anyio
    async def test_shellcheck_validation_success(self):
        """Test successful shellcheck validation."""
        cmd_req = CommandRequirement(
            command="echo 'properly quoted'", comment="Test successful validation"
        )
        self.interface.set_user_inputs(["n"])  # Decline to run

        result = await cmd_req.solve(SHELLCHECK_CONFIG, self.interface)

        # Should pass validation and reach user prompt
        assert not result.accepted  # Declined by user
        assert result.error is None  # No validation error

    @pytest.mark.no_subprocess_mocking
    @pytest.mark.anyio
    async def test_shellcheck_validation_failure(self):
        """Test shellcheck finding validation issues."""
        await initialize_plugins(config=SHELLCHECK_CONFIG, interface=self.interface)
        req = CommandRequirement(
            comment="Test",
            command="""
if then
  echo "broken"
fi
""",
        )
        self.interface.set_user_inputs(["n"])  # Decline sending error back to assistant

        result = await req.solve(SHELLCHECK_CONFIG, self.interface)

        assert not result.accepted
        assert "shellcheck validation failed" in result.error.lower()
        assert "Couldn't parse this if expression" in self.interface.get_all_output()

    @pytest.mark.anyio
    async def test_shellcheck_not_available(self, mock_subprocess):
        """Test graceful handling when shellcheck command is not found."""
        # Mock shellcheck command not found
        mock_subprocess.communicate.side_effect = FileNotFoundError(
            "shellcheck command not found"
        )

        config = SHELLCHECK_CONFIG
        req = CommandRequirement(command="echo test", comment="Test")
        interface = MockInterface()
        interface.set_user_inputs(["n"])  # Decline to run

        result = await req.solve(config, interface)

        # Should continue processing gracefully without shellcheck
        assert not result.accepted  # Declined by user
        assert result.error is None  # No plugin error


class TestShellcheckPluginIntegration:
    """Test shellcheck plugin integration with Solveig core."""

    @pytest.fixture(autouse=True)
    async def setup_shellcheck(self):
        """Load shellcheck plugin for each test."""
        self.interface = MockInterface()
        await initialize_plugins(config=SHELLCHECK_CONFIG, interface=self.interface)

    @pytest.mark.anyio
    async def test_plugin_registration(self):
        """Test that shellcheck plugin is properly registered."""
        # Should have the shellcheck before hook loaded
        assert len(hooks.HOOKS.before) >= 1
        hook_names = [hook[0].__name__ for hook in hooks.HOOKS.before]
        assert "check_command" in hook_names

    @pytest.mark.anyio
    async def test_plugin_requirement_filtering(self):
        """Test that shellcheck only runs for CommandRequirement."""

        # CommandRequirement with dangerous pattern should trigger shellcheck
        cmd_req = CommandRequirement(command="rm -rf /", comment="Test")
        self.interface.set_user_inputs(["n"])  # Decline sending error back to assistant
        result = await cmd_req.solve(SHELLCHECK_CONFIG, self.interface)

        # Should be stopped by shellcheck plugin
        assert not result.accepted
        assert "dangerous pattern" in result.error.lower()

        # Test that ReadRequirement doesn't trigger shellcheck
        read_req = ReadRequirement(
            path="/test/nonexistent.txt", metadata_only=True, comment="Test"
        )
        result = await read_req.solve(SHELLCHECK_CONFIG, self.interface)

        # Should not be stopped by shellcheck (file validation error is different)
        assert not result.accepted
        assert "does not exist" in result.error.lower()  # File error, not plugin error
