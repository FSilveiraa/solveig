"""
Tests for the refactored exception-based plugin system.
"""

import tempfile
from pathlib import Path

import pytest

from solveig.config import SolveigConfig
from solveig.exceptions import ProcessingError, SecurityError, ValidationError
from solveig.interface import SolveigInterface
from solveig.plugins import hooks, initialize_plugins
from solveig.schema import (
    ReadResult,
    WriteRequirement,
)
from solveig.schema.requirement import CommandRequirement, ReadRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio


class TestPluginExceptions:
    """Test plugin exception classes."""

    async def test_validation_error_inheritance(self):
        """Test that ValidationError inherits properly."""
        error = ValidationError("test message")
        assert str(error) == "test message"
        assert isinstance(error, ValidationError)
        assert isinstance(error, Exception)

    async def test_security_error_inheritance(self):
        """Test that SecurityError inherits from ValidationError."""
        error = SecurityError("security issue")
        assert str(error) == "security issue"
        assert isinstance(error, SecurityError)
        assert isinstance(error, ValidationError)

    async def test_processing_error_inheritance(self):
        """Test that ProcessingError inherits properly."""
        error = ProcessingError("processing failed")
        assert str(error) == "processing failed"
        assert isinstance(error, ProcessingError)
        assert isinstance(error, Exception)


class TestPluginHookSystem:
    """Test the exception-based plugin hook system."""

    @pytest.fixture(autouse=True)
    def clean_hooks(self):
        """Ensure a clean slate for all hook system tests."""
        hooks.clear_hooks()

    async def test_before_hook_validation_error(self):
        """Test that before hooks can raise ValidationError to stop processing."""
        # Setup
        interface = MockInterface(choices=[2])  # Decline if it gets to user

        hooks.clear_hooks()

        @hooks.before(requirements=(CommandRequirement,))
        async def failing_validator(
            config: SolveigConfig,
            interface: SolveigInterface,
            requirement: CommandRequirement,
        ):
            await interface.display_comment("I'm a plugin that fails on request")
            if "fail" in requirement.command:
                raise ValidationError("Command validation failed")

        # Manually activate the locally-defined hook for this test
        plugin_name = hooks._get_plugin_name_from_function(failing_validator)
        before_hooks, _ = hooks.HOOKS.all[plugin_name]
        hooks.HOOKS.before.extend(before_hooks)

        req = CommandRequirement(command="fail this command", comment="Test")

        # Execute
        result = await req.solve(DEFAULT_CONFIG, interface)

        # Verify
        assert not result.accepted
        assert result.error == "Pre-processing failed: Command validation failed"
        assert not result.success

    async def test_before_hook_security_error(self):
        """Test that before hooks can raise SecurityError for dangerous commands."""
        # Setup
        interface = MockInterface(choices=[2])

        hooks.clear_hooks()

        @hooks.before(requirements=(CommandRequirement,))
        async def security_validator(
            config: SolveigConfig,
            interface: MockInterface,
            requirement: CommandRequirement,
        ):
            if "rm -rf" in requirement.command:
                raise SecurityError("Dangerous command detected")

        # Manually activate the locally-defined hook for this test
        plugin_name = hooks._get_plugin_name_from_function(security_validator)
        before_hooks, _ = hooks.HOOKS.all[plugin_name]
        hooks.HOOKS.before.extend(before_hooks)

        req = CommandRequirement(command="rm -rf /important/data", comment="Test")

        # Execute
        result = await req.solve(DEFAULT_CONFIG, interface)

        # Verify
        assert not result.accepted
        assert result.error == "Pre-processing failed: Dangerous command detected"
        assert not result.success

    async def test_before_hook_success_continues(self):
        """Test that before hooks that don't raise exceptions allow processing to continue."""
        # Setup
        interface = MockInterface(choices=[2])  # Decline the command

        hooks.clear_hooks()

        @hooks.before(requirements=(CommandRequirement,))
        async def passing_validator(
            config: SolveigConfig,
            interface: MockInterface,
            requirement: CommandRequirement,
        ):
            # Just validate, don't throw
            assert requirement.command is not None
            await interface.display_text(f"command '{requirement.command}' exists")

        # Manually activate the locally-defined hook for this test
        plugin_name = hooks._get_plugin_name_from_function(passing_validator)
        before_hooks, _ = hooks.HOOKS.all[plugin_name]
        hooks.HOOKS.before.extend(before_hooks)

        req = CommandRequirement(command="echo hello", comment="Test")

        # Execute
        result = await req.solve(DEFAULT_CONFIG, interface)

        # Verify
        # Should get to user interaction (not stopped by plugin)
        assert not result.accepted  # Declined by user
        assert result.error is None  # No plugin error
        assert "command 'echo hello' exists" in interface.get_all_output()

    async def test_after_hook_processing_error(self, tmp_path):
        """Test that after hooks can raise ProcessingError."""
        # Setup
        interface = MockInterface(choices=[0])  # Accept the command

        hooks.clear_hooks()

        @hooks.after(requirements=(ReadRequirement,))
        async def failing_processor(
            config: SolveigConfig,
            interface: MockInterface,
            requirement: ReadRequirement,
            result: ReadResult,
        ):
            if result.accepted:
                raise ProcessingError("Post-processing failed")

        # Manually activate the locally-defined hook for this test
        plugin_name = hooks._get_plugin_name_from_function(failing_processor)
        _, after_hooks = hooks.HOOKS.all[plugin_name]
        hooks.HOOKS.after.extend(after_hooks)

        req = ReadRequirement(comment="Test", path=str(tmp_path), metadata_only=True)

        # Execute
        result = await req.solve(DEFAULT_CONFIG, interface)

        # Verify
        assert result.accepted  # Command was accepted originally
        assert "post-processing failed" in result.error.lower()

    async def test_multiple_before_hooks(self):
        """Test that multiple before hooks are executed in order."""
        # Setup
        execution_order = []
        interface = MockInterface(choices=[2])

        hooks.clear_hooks()

        @hooks.before(requirements=(CommandRequirement,))
        async def first_validator(config, interface, requirement):
            execution_order.append("first")

        @hooks.before(requirements=(CommandRequirement,))
        async def second_validator(config, interface, requirement):
            execution_order.append("second")

        # Manually activate the locally-defined hooks for this test
        plugin_name_1 = hooks._get_plugin_name_from_function(first_validator)
        before_hooks_1, _ = hooks.HOOKS.all[plugin_name_1]
        hooks.HOOKS.before.extend(before_hooks_1)

        plugin_name_2 = hooks._get_plugin_name_from_function(second_validator)
        before_hooks_2, _ = hooks.HOOKS.all[plugin_name_2]
        hooks.HOOKS.before.extend(before_hooks_2)

        req = CommandRequirement(command="echo test", comment="Test")

        # Execute
        await req.solve(DEFAULT_CONFIG, interface)

        # Verify
        assert execution_order == ["first", "second"]

    @pytest.mark.no_subprocess_mocking
    async def test_hook_requirement_filtering(self, tmp_path):
        """Test that hooks only run for specified requirement types."""
        # Setup
        called = []
        interface = MockInterface(choices=[2, 1])  # Don't run, don't send metadata

        hooks.clear_hooks()

        @hooks.before(requirements=(CommandRequirement,))
        async def command_only_hook(config, interface, requirement):
            called.append("command_hook")

        @hooks.before(requirements=(ReadRequirement,))
        async def read_only_hook(config, interface, requirement):
            called.append("read_hook")

        # Manually activate the locally-defined hooks for this test
        plugin_name_1 = hooks._get_plugin_name_from_function(command_only_hook)
        before_hooks_1, _ = hooks.HOOKS.all[plugin_name_1]
        hooks.HOOKS.before.extend(before_hooks_1)

        plugin_name_2 = hooks._get_plugin_name_from_function(read_only_hook)
        before_hooks_2, _ = hooks.HOOKS.all[plugin_name_2]
        hooks.HOOKS.before.extend(before_hooks_2)

        # Execute
        # Test with CommandRequirement
        cmd_req = CommandRequirement(command="echo test", comment="Test")
        await cmd_req.solve(DEFAULT_CONFIG, interface=interface)
        # Verify
        assert called == ["command_hook"]

        # Test with ReadRequirement
        test_file = tmp_path / "test_file.txt"
        test_file.write_text("content")
        read_req = ReadRequirement(
            path=str(test_file), metadata_only=True, comment="Test"
        )

        await read_req.solve(DEFAULT_CONFIG, interface=interface)

        # Verify
        assert called == ["command_hook", "read_hook"]
        assert len(called) == 2  # Each hook called once

    # Kinda unnecessary, but we need a no-op and an 'echo test' is pretty easy
    @pytest.mark.no_subprocess_mocking
    async def test_hook_without_requirement_filter(self, tmp_path):
        """Test that hooks without requirement filters run for all requirement types."""
        # Setup
        called = []
        interface = MockInterface(choices=[0, 0])  # Run command, read file

        def get_requirement_name(requirement) -> str:
            return f"universal_{type(requirement).__name__}"

        hooks.clear_hooks()

        @hooks.before()  # No schema filter
        async def universal_hook(config, interface, requirement):
            called.append(get_requirement_name(requirement))

        # Manually activate the locally-defined hook for this test
        plugin_name = hooks._get_plugin_name_from_function(universal_hook)
        before_hooks, _ = hooks.HOOKS.all[plugin_name]
        hooks.HOOKS.before.extend(before_hooks)

        # Test with different requirement types
        cmd_req = CommandRequirement(command="echo test", comment="Test")
        # task_req = TaskListRequirement(comment="Test")
        test_file = tmp_path / "test_file.txt"
        test_file.write_text("content")
        read_req = ReadRequirement(
            path=str(test_file), metadata_only=True, comment="Test"
        )

        await cmd_req.solve(DEFAULT_CONFIG, interface)
        await read_req.solve(DEFAULT_CONFIG, interface)

        # Verify
        assert get_requirement_name(cmd_req) in called
        assert get_requirement_name(read_req) in called


class TestPluginFiltering:
    """Test plugin filtering based on configuration."""

    @pytest.fixture(autouse=True)
    def clean_hooks(self):
        """Ensure a clean slate for all plugin filtering tests."""
        hooks.clear_hooks()

    @pytest.mark.no_file_mocking
    async def test_plugin_enabled_when_in_config(self):
        """Test that plugins are enabled when present in config.plugins."""
        # Create a test plugin
        called = []

        @hooks.before(requirements=(WriteRequirement,))
        async def test_plugin_hook(config, interface, requirement):
            called.append("test_plugin_executed")

        # Manually activate the locally-defined hook for this test
        plugin_name = hooks._get_plugin_name_from_function(test_plugin_hook)
        before_hooks, _ = hooks.HOOKS.all[plugin_name]
        hooks.HOOKS.before.extend(before_hooks)

        # Create config with plugin enabled
        config_with_plugin = SolveigConfig(
            url="test-url",
            api_key="test-key",
            plugins={"test_plugin_hook": {}},  # Enable the plugin
        )

        interface = MockInterface(choices=[0])

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file = Path(temp_dir) / "file.txt"
            assert not temp_file.exists()

            # Execute requirement
            req = WriteRequirement(
                comment="Test write with a plugin",
                path=str(temp_file),
                is_directory=False,
                content="bananas pineapples",
            )
            result = await req.solve(config_with_plugin, interface)
            assert temp_file.exists()

            # Verify plugin executed
            assert "test_plugin_executed" in called
            assert result.accepted
            assert result.error is None

            file_content = temp_file.read_text()
        assert file_content == "bananas pineapples"

    async def test_plugin_disabled_when_not_in_config(self):
        """Test that plugins are disabled when not present in config.plugins."""
        # Setup: Create a test plugin
        called = []

        @hooks.before(requirements=(CommandRequirement,))
        async def test_plugin_hook(config, interface, requirement):
            called.append("test_plugin_executed")

        # Create config WITHOUT plugin (empty plugins dict)
        config_without_plugin = SolveigConfig(
            url="test-url",
            api_key="test-key",
            plugins={},  # Plugin not listed, should be disabled
        )

        interface = MockInterface(choices=[2])

        # The hook is defined but never activated, so it should not run.

        # Execute requirement
        req = CommandRequirement(command="echo test", comment="Test")
        await req.solve(config_without_plugin, interface)

        # Verify plugin did NOT execute
        assert "test_plugin_executed" not in called
        assert len(called) == 0

    async def test_shellcheck_plugin_filtering(self):
        """
        Test specific shellcheck plugin filtering behavior.
        Note that this is so far the only instance where a unit test for a core component
        relies on a plugin, and we do it because the entire plugin import mechanism needs
        testing with actual plugin files
        """
        from solveig.plugins import initialize_plugins

        # Config without shellcheck (default state)
        config_no_shellcheck = SolveigConfig(
            url="test-url",
            api_key="test-key",
            # Shellcheck not configured
            plugins={"some-other_plugin": {}},
        )

        interface = MockInterface()
        # Initialize plugins with no plugins enabled
        await initialize_plugins(config=config_no_shellcheck, interface=interface)

        # Verify filtering message appears in output
        output_text = " ".join(interface.outputs)
        assert "'shellcheck': skipped" in output_text.lower()

        # Verify no hooks are active
        assert len(hooks.HOOKS.before) == 0
        assert len(hooks.HOOKS.after) == 0

    async def test_plugin_with_config_options(self):
        """Test that plugin configuration is passed correctly."""
        # Setup: Create a plugin that uses its config
        received_config = []

        @hooks.before(requirements=(CommandRequirement,))
        async def configurable_plugin_hook(config, interface, requirement):
            plugin_config = config.plugins.get("configurable_plugin_hook", {})
            received_config.append(plugin_config)

        # Create config with plugin options
        config_with_options = SolveigConfig(
            url="test-url",
            api_key="test-key",
            plugins={
                "configurable_plugin_hook": {
                    "option1": "value1",
                    "option2": 42,
                    "enabled": True,
                }
            },
        )

        interface = MockInterface(choices=[2])
        # Manually activate the locally-defined hook for this test
        plugin_name = hooks._get_plugin_name_from_function(configurable_plugin_hook)
        before_hooks, _ = hooks.HOOKS.all[plugin_name]
        hooks.HOOKS.before.extend(before_hooks)

        # Execute requirement
        req = CommandRequirement(command="echo test", comment="Test")
        await req.solve(config_with_options, interface)

        # Verify plugin received its configuration
        assert len(received_config) == 1
        assert received_config[0]["option1"] == "value1"
        assert received_config[0]["option2"] == 42
        assert received_config[0]["enabled"]

    async def test_no_duplicate_plugin_registration(self, load_plugins):
        """Test that multiple plugin loads don't create duplicate registrations."""

        test_config = SolveigConfig(
            url="test-url", api_key="test-key", plugins={"shellcheck": {}}
        )

        def count_hooks(plugin_name="shellcheck"):
            before, after = hooks.HOOKS.all[plugin_name]
            return len(before) + len(after)

        # Initialize plugins multiple times
        await load_plugins(test_config)
        first_load_count = count_hooks()

        await load_plugins(test_config)
        second_load_count = count_hooks()

        await load_plugins(test_config)
        third_load_count = count_hooks()

        # Registry should have same number of hooks after multiple loads
        assert first_load_count > 0  # Make sure we actually loaded something
        assert first_load_count == second_load_count == third_load_count, (
            "Should have exactly the same number of hooks after multiple reloads"
        )

        # And active hooks should match registry (since plugin is enabled)
        assert len(hooks.HOOKS.before) == first_load_count
