"""Tests for the tool plugin system — current API (list-based PLUGIN_TOOLS)."""

from unittest.mock import MagicMock, patch

import pytest

from solveig.config import SolveigConfig
from solveig.plugins.tools import (
    PLUGIN_TOOLS,
    config_model_of,
    load_and_filter_plugin_tools,
    plugin_tool_name,
)
from solveig.plugins.tools.tree import TreeTool
from solveig.tools.base import ToolConfig

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Tool plugin filtering (mocked registry)
# ---------------------------------------------------------------------------


class TestToolPluginFiltering:
    @pytest.fixture(autouse=True)
    def clean_tools(self):
        PLUGIN_TOOLS.clear()

    async def test_tool_discovered_and_enabled_when_in_config(self):
        """A tool discovered by the rescan is registered."""
        from solveig.plugins.tools import FunctionTool

        async def my_tool_fn(): ...

        def fake_rescan(path):
            PLUGIN_TOOLS.append(FunctionTool(my_tool_fn))
            return (1, 0, [])

        config = SolveigConfig(
            cli_args=[], api={"url": "http://x", "key": "k"}
        )
        with patch(
            "solveig.plugins.tools.rescan_and_load_plugins",
            side_effect=fake_rescan,
        ):
            load_and_filter_plugin_tools(config)

        names = [plugin_tool_name(t) for t in PLUGIN_TOOLS]
        assert "my_tool_fn" in names
        assert config_model_of(PLUGIN_TOOLS[0]) is ToolConfig

    async def test_tool_discovered_but_not_in_config(self):
        """A tool discovered by the rescan is still registered."""
        from solveig.plugins.tools import FunctionTool

        async def my_tool_fn(): ...

        def fake_rescan(path):
            PLUGIN_TOOLS.append(FunctionTool(my_tool_fn))
            return (1, 0, [])

        config = SolveigConfig(
            cli_args=[], api={"url": "http://x", "key": "k"}
        )
        with patch(
            "solveig.plugins.tools.rescan_and_load_plugins",
            side_effect=fake_rescan,
        ):
            load_and_filter_plugin_tools(config)

        assert len(PLUGIN_TOOLS) == 1
        assert plugin_tool_name(PLUGIN_TOOLS[0]) == "my_tool_fn"

    @pytest.mark.no_file_mocking
    async def test_tree_plugin_loaded_when_in_config(self):
        """The real tree plugin is discovered."""
        SolveigConfig.compose_core_tools()
        SolveigConfig.compose_plugin_tools()
        config = SolveigConfig(
            cli_args=[],
            api={"url": "test-url", "key": "test-key"},
            plugins={"tools": {"tree": {}}},
        )
        load_and_filter_plugin_tools(config)

        names = [plugin_tool_name(t) for t in PLUGIN_TOOLS]
        assert "tree" in names
