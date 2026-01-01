"""
Tests for the shellcheck plugin.
This tests the shellcheck plugin in isolation from other plugins.
"""

# Config with shellcheck plugin enabled - manually create to avoid copy issues
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest

from solveig.plugins import hooks
from solveig.plugins.hooks.shellcheck import is_obviously_dangerous
from solveig.schema.tool import (
    CommandTool,
    ReadTool,
)
from tests.mocks import DEFAULT_CONFIG, MockInterface

SHELLCHECK_CONFIG = replace(DEFAULT_CONFIG, plugins={"shellcheck": {}})


pytestmark = [pytest.mark.anyio]


class TestShellcheckPlugin:
    """Test the shellcheck plugin functionality in isolation."""

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
    async def test_security_error_message_format(self, tmp_path, load_plugins):
        """Test that dangerous commands produce properly formatted error messages."""
        interface = MockInterface()
        await load_plugins(SHELLCHECK_CONFIG)
        req = CommandTool(
            command=f"mkfs.ext4 {tmp_path}/__non-existent-path__/sdx1",
            comment="Test dangerous command error formatting",
        )
        interface.choices.extend([1])  # Decline sending error back to assistant

        result = await req.solve(SHELLCHECK_CONFIG, interface)

        assert not result.accepted
        assert "dangerous pattern" in result.error.lower()
        assert (
            "mkfs.ext4" in result.error
        )  # Should mention the specific dangerous command
        assert not result.success

    @pytest.mark.no_subprocess_mocking
    async def test_normal_command_passes_validation(self, load_plugins):
        """
        Test that normal commands pass shellcheck validation.
        Note that this test runs the actual shellcheck command on the user's shell, it doesn't
        just get rid of the mock's exception, and will likely fail if shellcheck isn't installed
        """
        interface = MockInterface()
        await load_plugins(SHELLCHECK_CONFIG)
        cmd_req = CommandTool(
            command="echo 'hello world'", comment="Test normal command"
        )
        interface.choices.extend([2])  # Decline to run

        # Mock user declining to run the command (we just want to test plugin validation)
        result = await cmd_req.solve(SHELLCHECK_CONFIG, interface)

        # Should reach user prompt (not stopped by plugin) and be declined by user
        assert not result.accepted
        assert result.error is None  # No plugin validation error

    @pytest.mark.no_subprocess_mocking
    async def test_shellcheck_validation_success(self, load_plugins):
        """Test successful shellcheck validation."""
        interface = MockInterface()
        await load_plugins(SHELLCHECK_CONFIG)
        cmd_req = CommandTool(
            command="echo 'properly quoted'", comment="Test successful validation"
        )
        interface.choices.extend([2])  # Decline to run

        result = await cmd_req.solve(SHELLCHECK_CONFIG, interface)

        # Should pass validation and reach user prompt
        assert not result.accepted  # Declined by user
        assert result.error is None  # No validation error

    @pytest.mark.no_subprocess_mocking
    async def test_shellcheck_validation_failure(self, load_plugins):
        """Test shellcheck finding validation issues."""
        interface = MockInterface()
        await load_plugins(SHELLCHECK_CONFIG)
        req = CommandTool(
            comment="Test",
            command="""
if then
  echo "broken"
fi
""",
        )
        interface.choices.extend([1])  # Decline sending error back to assistant

        result = await req.solve(SHELLCHECK_CONFIG, interface)

        assert not result.accepted
        assert "execution cancelled due to shellcheck" in result.error.lower()
        assert "Couldn't parse this if expression" in interface.get_all_output()

    @pytest.mark.no_subprocess_mocking
    async def test_shellcheck_not_available(self, load_plugins):
        """Test graceful handling when shellcheck command is not found."""
        await load_plugins(SHELLCHECK_CONFIG)
        with patch(
            "asyncio.create_subprocess_shell", new_callable=AsyncMock
        ) as mock_create_subprocess_shell:
            mock_process = AsyncMock()
            mock_process.returncode = 127
            mock_process.communicate.return_value = (
                b"",  # stdout
                b"/bin/sh: shellcheck: command not found",  # stderr
            )
            mock_create_subprocess_shell.return_value = mock_process

            config = SHELLCHECK_CONFIG
            req = CommandTool(command="echo test", comment="Test")
            interface = MockInterface()
            interface.choices.extend([2])  # Decline to run the command

            result = await req.solve(config, interface)

            # Verify the warning was displayed
            output = interface.get_all_output()
            assert all(
                sig in output.lower()
                for sig in [
                    "warning",
                    "shellcheck plugin is enabled",
                    "command is not available.",
                ]
            )

            # Verify that the command was not stopped by the plugin, but by the user
            assert not result.accepted
            assert result.error is None  # No plugin error should be raised


class TestShellcheckPluginIntegration:
    """Test shellcheck plugin integration with Solveig core."""

    async def test_plugin_registration(self, load_plugins):
        """Test that shellcheck plugin is properly registered."""
        await load_plugins(SHELLCHECK_CONFIG)
        # Should have the shellcheck before hook loaded
        assert len(hooks.HOOKS.before) >= 1
        hook_names = [hook[0].__name__ for hook in hooks.HOOKS.before]
        assert "check_command" in hook_names

    @pytest.mark.no_subprocess_mocking
    async def test_plugin_requirement_filtering(self, tmp_path, load_plugins):
        """Test that shellcheck only runs for CommandRequirement."""
        interface = MockInterface()
        await load_plugins(SHELLCHECK_CONFIG)

        # CommandRequirement with dangerous pattern should trigger shellcheck
        cmd_req = CommandTool(
            command="""
if then
  echo "broken"
fi
""",
            comment="Test shellcheck error",
        )
        interface.choices.extend([1])  # Decline sending error back to assistant
        result = await cmd_req.solve(SHELLCHECK_CONFIG, interface)

        # Should be stopped by shellcheck plugin
        assert not result.accepted
        assert "execution cancelled due to shellcheck" in result.error.lower()

        # Test that ReadRequirement doesn't trigger shellcheck
        read_req = ReadTool(path=str(tmp_path), metadata_only=True, comment="Test read")
        interface.choices.extend([1])  # Decline sending metadata
        result = await read_req.solve(SHELLCHECK_CONFIG, interface)

        # Should not be stopped by shellcheck, but declined by user
        assert not result.accepted
        assert result.error is None  # No plugin error
