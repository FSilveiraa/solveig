"""Tests for the exception-based plugin hook system."""

from unittest.mock import patch

import pytest

from solveig.config import SolveigConfig
from solveig.exceptions import ProcessingError, SecurityError, ValidationError
from solveig.plugins import hooks, initialize_plugins
from solveig.plugins.hooks import load_and_filter_hooks
from solveig.schema.tool import CommandTool, ReadTool
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Hook system behaviour
# Hooks are registered directly into HOOKS.before / HOOKS.after —
# no file loading needed to test execution semantics.
# ---------------------------------------------------------------------------


class TestPluginHookSystem:
    @pytest.fixture(autouse=True)
    def clean_hooks(self):
        hooks.clear_hooks()

    async def test_before_hook_validation_error(self):
        """ValidationError from a before hook stops processing."""

        async def failing_validator(config, interface, tool):
            if "fail" in tool.command:
                raise ValidationError("Command validation failed")

        hooks.HOOKS.before.append((failing_validator, (CommandTool,)))

        result = await CommandTool(command="fail this command", comment="Test").solve(
            DEFAULT_CONFIG, MockInterface()
        )

        assert not result.accepted
        assert result.error == "Pre-processing failed: Command validation failed"
        assert not result.success

    async def test_before_hook_security_error(self):
        """SecurityError from a before hook stops processing."""

        async def security_validator(config, interface, tool):
            if "rm -rf" in tool.command:
                raise SecurityError("Dangerous command detected")

        hooks.HOOKS.before.append((security_validator, (CommandTool,)))

        result = await CommandTool(
            command="rm -rf /important/data", comment="Test"
        ).solve(DEFAULT_CONFIG, MockInterface())

        assert not result.accepted
        assert result.error == "Pre-processing failed: Dangerous command detected"

    async def test_before_hook_success_continues_to_user(self):
        """A before hook that doesn't raise lets processing reach the user."""
        side_effects = []

        async def passing_validator(config, interface, tool):
            side_effects.append(f"validated: {tool.command}")

        hooks.HOOKS.before.append((passing_validator, (CommandTool,)))

        result = await CommandTool(command="echo hello", comment="Test").solve(
            DEFAULT_CONFIG,
            MockInterface(choices=[2]),  # user declines
        )

        assert not result.accepted  # declined by user, not blocked by hook
        assert result.error is None  # no hook error
        assert side_effects == ["validated: echo hello"]

    @pytest.mark.no_file_mocking
    async def test_after_hook_processing_error(self, tmp_path):
        """ProcessingError from an after hook is attached to the result."""

        async def failing_processor(config, interface, tool, result):
            if result.accepted:
                raise ProcessingError("Post-processing failed")

        hooks.HOOKS.after.append((failing_processor, (ReadTool,)))

        result = await ReadTool(
            comment="Test", path=str(tmp_path), metadata_only=True
        ).solve(DEFAULT_CONFIG, MockInterface(choices=[0]))

        assert result.accepted
        assert "post-processing failed" in result.error.lower()

    async def test_multiple_before_hooks_run_in_order(self):
        """Multiple before hooks execute in the order they were registered."""
        execution_order = []

        async def first_hook(config, interface, tool):
            execution_order.append("first")

        async def second_hook(config, interface, tool):
            execution_order.append("second")

        hooks.HOOKS.before.append((first_hook, (CommandTool,)))
        hooks.HOOKS.before.append((second_hook, (CommandTool,)))

        await CommandTool(command="echo test", comment="Test").solve(
            DEFAULT_CONFIG, MockInterface(choices=[2])
        )

        assert execution_order == ["first", "second"]

    @pytest.mark.no_file_mocking
    async def test_hook_tool_filtering(self, tmp_path):
        """Hooks with a tools filter only fire for the specified tool type."""
        called = []

        async def command_hook(config, interface, tool):
            called.append("command_hook")

        async def read_hook(config, interface, tool):
            called.append("read_hook")

        hooks.HOOKS.before.append((command_hook, (CommandTool,)))
        hooks.HOOKS.before.append((read_hook, (ReadTool,)))

        await CommandTool(command="echo test", comment="Test").solve(
            DEFAULT_CONFIG, MockInterface(choices=[2])
        )
        assert called == ["command_hook"]

        (tmp_path / "f.txt").write_text("content")
        await ReadTool(
            path=str(tmp_path / "f.txt"), metadata_only=True, comment="Test"
        ).solve(DEFAULT_CONFIG, MockInterface(choices=[1]))
        assert called == ["command_hook", "read_hook"]

    @pytest.mark.no_file_mocking
    @pytest.mark.no_subprocess_mocking
    async def test_hook_without_tool_filter_runs_for_all(self, tmp_path):
        """A hook registered with no tool filter runs for every tool type."""
        called = []

        async def universal_hook(config, interface, tool):
            called.append(type(tool).__name__)

        hooks.HOOKS.before.append((universal_hook, None))

        (tmp_path / "f.txt").write_text("content")
        await CommandTool(command="echo test", comment="Test").solve(
            DEFAULT_CONFIG, MockInterface(choices=[0])
        )
        await ReadTool(
            path=str(tmp_path / "f.txt"), metadata_only=True, comment="Test"
        ).solve(DEFAULT_CONFIG, MockInterface(choices=[0]))

        assert "CommandTool" in called
        assert "ReadTool" in called


# ---------------------------------------------------------------------------
# Plugin filtering
# The load/filter pipeline is tested by mocking rescan_and_load_plugins so it
# pre-populates HOOKS.all (as a real plugin import would), then letting the
# filtering loop in load_and_filter_hooks run for real.
# ---------------------------------------------------------------------------


class TestPluginFiltering:
    @pytest.fixture(autouse=True)
    def clean_hooks(self):
        hooks.clear_hooks()

    async def test_plugin_enabled_when_in_config(self):
        """Plugins in config.plugins are activated after loading."""
        called = []

        async def my_hook(config, interface, tool):
            called.append("executed")

        async def fake_rescan(**_):
            hooks.HOOKS.all["my_plugin"][0].append((my_hook, (CommandTool,)))

        config = DEFAULT_CONFIG.with_(plugins={"my_plugin": {}})
        with patch(
            "solveig.plugins.hooks.rescan_and_load_plugins", side_effect=fake_rescan
        ):
            await load_and_filter_hooks(config, MockInterface())

        assert len(hooks.HOOKS.before) == 1

        await CommandTool(command="echo test", comment="Test").solve(
            config, MockInterface(choices=[2])
        )
        assert called == ["executed"]

    async def test_plugin_disabled_when_not_in_config(self):
        """Plugins absent from config.plugins are imported but not activated."""
        called = []

        async def my_hook(config, interface, tool):
            called.append("should_not_run")

        async def fake_rescan(**_):
            hooks.HOOKS.all["my_plugin"][0].append((my_hook, (CommandTool,)))

        config = DEFAULT_CONFIG.with_(plugins={})  # my_plugin not listed
        with patch(
            "solveig.plugins.hooks.rescan_and_load_plugins", side_effect=fake_rescan
        ):
            await load_and_filter_hooks(config, MockInterface())

        assert len(hooks.HOOKS.before) == 0

        await CommandTool(command="echo test", comment="Test").solve(
            config, MockInterface(choices=[2])
        )
        assert called == []

    async def test_shellcheck_plugin_skipped_when_not_in_config(self):
        """The real shellcheck plugin is skipped when absent from config.plugins."""
        config = SolveigConfig(
            url="test-url",
            api_key="test-key",
            plugins={"some_other_plugin": {}},
        )

        interface = MockInterface()
        await initialize_plugins(config=config, interface=interface)

        assert "'shellcheck': skipped" in " ".join(interface.outputs).lower()
        assert len(hooks.HOOKS.before) == 0
        assert len(hooks.HOOKS.after) == 0

    async def test_plugin_receives_its_config_options(self):
        """The hook receives config and can read its own config.plugins entry."""
        received = []

        async def configurable_hook(config, interface, tool):
            received.append(config.plugins.get("my_plugin", {}))

        async def fake_rescan(**_):
            hooks.HOOKS.all["my_plugin"][0].append((configurable_hook, (CommandTool,)))

        config = DEFAULT_CONFIG.with_(
            plugins={"my_plugin": {"option1": "value1", "option2": 42}}
        )
        with patch(
            "solveig.plugins.hooks.rescan_and_load_plugins", side_effect=fake_rescan
        ):
            await load_and_filter_hooks(config, MockInterface())

        await CommandTool(command="echo test", comment="Test").solve(
            config, MockInterface(choices=[2])
        )

        assert received == [{"option1": "value1", "option2": 42}]

    async def test_no_duplicate_plugin_registration(self, load_plugins):
        """Multiple calls to load_plugins don't duplicate hook entries."""
        config = SolveigConfig(
            url="test-url", api_key="test-key", plugins={"shellcheck": {}}
        )

        def hook_count():
            before, after = hooks.HOOKS.all["shellcheck"]
            return len(before) + len(after)

        await load_plugins(config)
        count_after_first = hook_count()

        await load_plugins(config)
        await load_plugins(config)

        assert count_after_first > 0
        assert hook_count() == count_after_first
        assert len(hooks.HOOKS.before) == count_after_first
