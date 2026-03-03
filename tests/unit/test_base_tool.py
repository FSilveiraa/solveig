"""Unit tests for BaseTool.solve() orchestration logic."""

from unittest.mock import AsyncMock, patch

import pytest

from solveig.exceptions import PluginException
from solveig.plugins.hooks import PLUGIN_HOOKS
from solveig.schema.tool import CommandTool
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Execution-failure path (base.py lines 122-131)
# ---------------------------------------------------------------------------


class TestExecutionFailurePath:
    """Tests for the exception handler wrapping actually_solve."""

    async def test_user_sends_error_back(self):
        """When actually_solve raises and user chooses Yes, error details are appended."""
        with patch.object(
            CommandTool,
            "actually_solve",
            new_callable=AsyncMock,
            side_effect=RuntimeError("something went wrong"),
        ):
            result = await CommandTool(command="ls", comment="Test").solve(
                DEFAULT_CONFIG,
                MockInterface(choices=[0]),  # 0 = Yes
            )

        assert not result.accepted
        assert result.error == "Execution error: something went wrong"

    async def test_user_suppresses_error(self):
        """When actually_solve raises and user chooses No, only generic message returned."""
        with patch.object(
            CommandTool,
            "actually_solve",
            new_callable=AsyncMock,
            side_effect=RuntimeError("something went wrong"),
        ):
            result = await CommandTool(command="ls", comment="Test").solve(
                DEFAULT_CONFIG,
                MockInterface(choices=[1]),  # 1 = No
            )

        assert not result.accepted
        assert result.error == "Execution error"


# ---------------------------------------------------------------------------
# Before-hook PluginException path (base.py lines 112-116)
# ---------------------------------------------------------------------------


class TestBeforeHookPluginException:
    """Tests for bare PluginException (non-ValidationError) raised from a before-hook."""

    @pytest.fixture(autouse=True)
    def clean_hooks(self):
        PLUGIN_HOOKS.clear()

    async def test_plugin_exception_returns_plugin_error(self):
        """A bare PluginException from a before hook returns 'Plugin error: ...'."""

        async def bad_hook(config, interface, tool):
            raise PluginException("something broke in plugin")

        PLUGIN_HOOKS.before.append((bad_hook, (CommandTool,)))

        result = await CommandTool(command="ls", comment="Test").solve(
            DEFAULT_CONFIG, MockInterface()
        )

        assert not result.accepted
        assert result.error == "Plugin error: something broke in plugin"
