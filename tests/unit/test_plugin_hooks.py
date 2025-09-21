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
from solveig.schema import CommandResult, WriteRequirement
from solveig.schema.requirements import CommandRequirement, ReadRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface


class TestPluginExceptions:
    """Test plugin exception classes."""

    def test_validation_error_inheritance(self):
        """Test that ValidationError inherits properly."""
        error = ValidationError("test message")
        assert str(error) == "test message"
        assert isinstance(error, ValidationError)
        assert isinstance(error, Exception)

    def test_security_error_inheritance(self):
        """Test that SecurityError inherits from ValidationError."""
        error = SecurityError("security issue")
        assert str(error) == "security issue"
        assert isinstance(error, SecurityError)
        assert isinstance(error, ValidationError)

    def test_processing_error_inheritance(self):
        """Test that ProcessingError inherits properly."""
        error = ProcessingError("processing failed")
        assert str(error) == "processing failed"
        assert isinstance(error, ProcessingError)
        assert isinstance(error, Exception)


class TestPluginHookSystem:
    """Test the exception-based plugin hook system."""

    def test_before_hook_validation_error(self):
        """Test that before hooks can raise ValidationError to stop processing."""
        # Setup
        interface = MockInterface()

        @hooks.before(requirements=(CommandRequirement,))
        def failing_validator(
            config: SolveigConfig,
            interface: SolveigInterface,
            requirement: CommandRequirement,
        ):
            interface.display_comment("I'm a plugin that fails on request")
            if "fail" in requirement.command:
                raise ValidationError("Command validation failed")

        hooks.load_and_filter_hooks(
            interface=interface, enabled_plugins={"failing_validator"}
        )

        req = CommandRequirement(command="fail this command", comment="Test")
        interface.set_user_inputs(["n"])  # Decline if it gets to user

        # Execute
        result = req.solve(DEFAULT_CONFIG, interface)

        # Verify
        assert not result.accepted
        assert result.error == "Pre-processing failed: Command validation failed"
        assert not result.success

    def test_before_hook_security_error(self):
        """Test that before hooks can raise SecurityError for dangerous commands."""
        # Setup
        interface = MockInterface()

        @hooks.before(requirements=(CommandRequirement,))
        def security_validator(
            config: SolveigConfig,
            interface: MockInterface,
            requirement: CommandRequirement,
        ):
            if "rm -rf" in requirement.command:
                raise SecurityError("Dangerous command detected")

        hooks.load_and_filter_hooks(
            interface=interface, enabled_plugins={"security_validator"}
        )

        req = CommandRequirement(command="rm -rf /important/data", comment="Test")
        interface.set_user_inputs(["n"])

        # Execute
        result = req.solve(DEFAULT_CONFIG, interface)

        # Verify
        assert not result.accepted
        assert result.error == "Pre-processing failed: Dangerous command detected"
        assert not result.success

    def test_before_hook_success_continues(self):
        """Test that before hooks that don't raise exceptions allow processing to continue."""
        # Setup
        interface = MockInterface()

        @hooks.before(requirements=(CommandRequirement,))
        def passing_validator(
            config: SolveigConfig,
            interface: MockInterface,
            requirement: CommandRequirement,
        ):
            # Just validate, don't throw
            assert requirement.command is not None
            interface.show(f"command '{requirement.command}' exists")

        hooks.load_and_filter_hooks(
            interface=interface, enabled_plugins={"passing_validator"}
        )

        req = CommandRequirement(command="echo hello", comment="Test")
        interface.set_user_inputs(["n"])  # Decline the command

        # Execute
        result = req.solve(DEFAULT_CONFIG, interface)

        # Verify
        # Should get to user interaction (not stopped by plugin)
        assert not result.accepted  # Declined by user
        assert result.error is None  # No plugin error
        assert "command 'echo hello' exists" in interface.get_all_output()

    def test_after_hook_processing_error(self):
        """Test that after hooks can raise ProcessingError."""
        # Setup
        interface = MockInterface()

        @hooks.after(requirements=(CommandRequirement,))
        def failing_processor(
            config: SolveigConfig,
            interface: MockInterface,
            requirement: CommandRequirement,
            result: CommandResult,
        ):
            if result.accepted:
                raise ProcessingError("Post-processing failed")

        # Activate the hook by filtering (all hooks enabled by default)
        hooks.load_and_filter_hooks(
            interface=interface, enabled_plugins={"failing_processor"}
        )

        req = CommandRequirement(command="echo hello", comment="Test")
        interface.set_user_inputs(["y", "y"])  # Accept the command

        # Execute
        result = req.solve(DEFAULT_CONFIG, interface)

        # Verify
        assert result.accepted  # Command was accepted originally
        assert result.error == "Post-processing failed: Post-processing failed"

    def test_multiple_before_hooks(self):
        """Test that multiple before hooks are executed in order."""
        # Setup
        execution_order = []
        interface = MockInterface()

        @hooks.before(requirements=(CommandRequirement,))
        def first_validator(config, interface, requirement):
            execution_order.append("first")

        @hooks.before(requirements=(CommandRequirement,))
        def second_validator(config, interface, requirement):
            execution_order.append("second")

        hooks.load_and_filter_hooks(
            interface=interface, enabled_plugins={"second_validator", "first_validator"}
        )

        req = CommandRequirement(command="echo test", comment="Test")
        interface.set_user_inputs(["n"])

        # Execute
        req.solve(DEFAULT_CONFIG, interface)

        # Verify
        assert execution_order == ["first", "second"]

    def test_hook_requirement_filtering(self):
        """Test that hooks only run for specified requirement types."""
        # Setup
        called = []
        interface = MockInterface()

        @hooks.before(requirements=(CommandRequirement,))
        def command_only_hook(config, interface, requirement):
            called.append("command_hook")

        @hooks.before(requirements=(ReadRequirement,))
        def read_only_hook(config, interface, requirement):
            called.append("read_hook")

        # Activate the hooks by filtering (all registered hooks enabled by default)
        hooks.load_and_filter_hooks(
            interface=MockInterface(),
            enabled_plugins={"command_only_hook", "read_only_hook"},
        )

        # Execute
        # Test with CommandRequirement
        cmd_req = CommandRequirement(command="echo test", comment="Test")
        interface.set_user_inputs(["n"])
        cmd_req.solve(DEFAULT_CONFIG, interface=interface)
        # Verify
        assert called == ["command_hook"]

        # Test with ReadRequirement
        read_req = ReadRequirement(
            path="/test/file.txt", metadata_only=True, comment="Test"
        )

        interface.set_user_inputs(["n"])
        read_req.solve(DEFAULT_CONFIG, interface=interface)

        # Verify
        assert called == ["command_hook", "read_hook"]
        assert len(called) == 2  # Each hook called once

    def test_hook_without_requirement_filter(self):
        """Test that hooks without requirement filters run for all requirement types."""
        # Setup
        called = []
        interface = MockInterface()

        def get_requirement_name(requirement) -> str:
            return f"universal_{type(requirement).__name__}"

        @hooks.before()  # No schema filter
        def universal_hook(config, interface, requirement):
            called.append(get_requirement_name(requirement))

        hooks.load_and_filter_hooks(
            interface=interface, enabled_plugins={"universal_hook"}
        )

        # Test with different requirement types
        cmd_req = CommandRequirement(command="echo test", comment="Test")
        read_req = ReadRequirement(
            path="/test/file.txt", metadata_only=True, comment="Test"
        )

        # Execute
        interface.set_user_inputs(["n"])
        cmd_req.solve(DEFAULT_CONFIG, interface)

        interface.set_user_inputs(["n"])
        read_req.solve(DEFAULT_CONFIG, interface)

        # Verify
        assert get_requirement_name(cmd_req) in called
        assert get_requirement_name(read_req) in called


class TestPluginFiltering:
    """Test plugin filtering based on configuration."""

    @pytest.mark.no_file_mocking
    def test_plugin_enabled_when_in_config(self):
        """Test that plugins are enabled when present in config.plugins."""
        # Create a test plugin
        called = []

        @hooks.before(requirements=(WriteRequirement,))
        def test_plugin_hook(config, interface, requirement):
            called.append("test_plugin_executed")

        # Create config with test plugin enabled (uses function name)
        config_with_plugin = SolveigConfig(
            url="test-url",
            api_key="test-key",
            plugins={"test_plugin_hook": {}},  # Plugin enabled by function name
        )

        interface = MockInterface()
        # Filter to enable only the test plugin
        hooks.load_and_filter_hooks(
            interface=interface, enabled_plugins=config_with_plugin
        )

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
            interface.set_user_inputs(["y", "y"])  # write file, send back
            result = req.solve(config_with_plugin, interface)
            assert temp_file.exists()

            # Verify plugin executed
            assert "test_plugin_executed" in called
            assert result.accepted
            assert result.error is None

            file_content = temp_file.read_text()
        assert file_content == "bananas pineapples"

    def test_plugin_disabled_when_not_in_config(self):
        """Test that plugins are disabled when not present in config.plugins."""
        # Setup: Create a test plugin
        called = []

        @hooks.before(requirements=(CommandRequirement,))
        def test_plugin_hook(config, interface, requirement):
            called.append("test_plugin_executed")

        # Create config WITHOUT plugin (empty plugins dict)
        config_without_plugin = SolveigConfig(
            url="test-url",
            api_key="test-key",
            plugins={},  # Plugin not listed, should be disabled
        )

        interface = MockInterface()

        # Apply filtering
        hooks.load_and_filter_hooks(
            enabled_plugins=config_without_plugin, interface=interface
        )

        # Execute requirement
        req = CommandRequirement(command="echo test", comment="Test")
        interface.set_user_inputs(["n"])
        req.solve(config_without_plugin, interface)

        # Verify plugin did NOT execute
        assert "test_plugin_executed" not in called
        assert len(called) == 0

    def test_shellcheck_plugin_filtering(self):
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
        initialize_plugins(config=config_no_shellcheck, interface=interface)

        # Verify filtering message appears in output
        output_text = " ".join(interface.outputs)
        assert "'shellcheck': skipped" in output_text.lower()

        # Verify no hooks are active
        assert len(hooks.HOOKS.before) == 0
        assert len(hooks.HOOKS.after) == 0

    def test_plugin_with_config_options(self):
        """Test that plugin configuration is passed correctly."""
        # Setup: Create a plugin that uses its config
        received_config = []

        @hooks.before(requirements=(CommandRequirement,))
        def configurable_plugin_hook(config, interface, requirement):
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

        interface = MockInterface()
        hooks.load_and_filter_hooks(
            enabled_plugins=config_with_options, interface=interface
        )

        # Execute requirement
        req = CommandRequirement(command="echo test", comment="Test")
        interface.set_user_inputs(["n"])
        req.solve(config_with_options, interface)

        # Verify plugin received its configuration
        assert len(received_config) == 1
        assert received_config[0]["option1"] == "value1"
        assert received_config[0]["option2"] == 42
        assert received_config[0]["enabled"]

    def test_no_duplicate_plugin_registration(self):
        """Test that multiple plugin loads don't create duplicate registrations."""

        interface = MockInterface()
        test_config = SolveigConfig(
            url="test-url", api_key="test-key", plugins={"shellcheck": {}}
        )

        def count_hooks(plugin_name="shellcheck"):
            before, after = hooks.HOOKS.all_hooks[plugin_name]
            return len(before) + len(after)

        # Initialize plugins multiple times
        initialize_plugins(config=test_config, interface=interface)
        first_load_count = count_hooks()

        initialize_plugins(config=test_config, interface=interface)
        second_load_count = count_hooks()

        initialize_plugins(config=test_config, interface=interface)
        third_load_count = count_hooks()

        # Registry should have same number of hooks after multiple loads
        assert (
            first_load_count == second_load_count == third_load_count
        ), "Should have exactly the same number of hooks after multiple reloads"

        # And active hooks should match registry (since plugin is enabled)
        assert len(hooks.HOOKS.before) == first_load_count
