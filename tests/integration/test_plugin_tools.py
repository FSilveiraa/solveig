"""Tests for the tool plugin system."""

from unittest.mock import MagicMock, patch

import pytest

from solveig.config import SolveigConfig
from solveig.plugins.tools import PLUGIN_TOOLS, load_and_filter_tools
from solveig.plugins.tools.tree import TreeTool
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Tool plugin filtering
# ---------------------------------------------------------------------------


class TestToolPluginFiltering:
    """`load_and_filter_tools` just discovers + reports; live visibility is
    decided per-step by `is_tool_active` (`tools/available.py`), which reads
    `PLUGIN_TOOLS.owners` against `ctx.deps.config.plugins` directly - there's
    no separate "active" set to keep in sync. These tests assert the same
    membership check `is_tool_active` performs."""

    @pytest.fixture(autouse=True)
    def clean_tools(self):
        PLUGIN_TOOLS.clear()

    async def test_tool_discovered_and_enabled_when_in_config(self):
        """A tool discovered by the rescan is registered and its plugin is enabled in config."""
        mock_tool_cls = MagicMock(__name__="my_tool")

        async def fake_rescan(**_):
            PLUGIN_TOOLS.register(mock_tool_cls)

        config = DEFAULT_CONFIG.with_(plugins={"my_tool": {}})
        with patch(
            "solveig.plugins.tools.rescan_and_load_plugins", side_effect=fake_rescan
        ):
            await load_and_filter_tools(config, MockInterface())

        assert PLUGIN_TOOLS.all["my_tool"] is mock_tool_cls
        assert PLUGIN_TOOLS.owners["my_tool"] in config.plugins

    async def test_tool_discovered_but_disabled_when_not_in_config(self):
        """A tool discovered by the rescan is still registered even if its plugin is absent from config."""
        mock_tool_cls = MagicMock(__name__="my_tool")

        async def fake_rescan(**_):
            PLUGIN_TOOLS.register(mock_tool_cls)

        config = DEFAULT_CONFIG.with_(plugins={})
        with patch(
            "solveig.plugins.tools.rescan_and_load_plugins", side_effect=fake_rescan
        ):
            await load_and_filter_tools(config, MockInterface())

        assert "my_tool" in PLUGIN_TOOLS.all
        assert PLUGIN_TOOLS.owners["my_tool"] not in config.plugins

    async def test_tree_plugin_skipped_when_not_in_config(self):
        """The real tree plugin's owner is absent from config.plugins."""
        SolveigConfig.bootstrap()
        config = SolveigConfig(
            url="test-url",
            api_key="test-key",
            plugins={"some_other_plugin": {}},
        )
        await load_and_filter_tools(config=config, interface=MockInterface())

        assert PLUGIN_TOOLS.owners["tree"] not in config.plugins

    async def test_tree_plugin_loaded_when_in_config(self):
        """The real tree plugin is discovered and its owner is enabled in config.plugins."""
        SolveigConfig.bootstrap()
        config = SolveigConfig(
            url="test-url",
            api_key="test-key",
            plugins={"tree": {}},
        )
        await load_and_filter_tools(config=config, interface=MockInterface())

        # `tree` is a @tool-decorated BaseTool subclass (TreeTool) now, keyed
        # by its dispatch name (`TreeTool.tool_name()` -> "tree"), not by the
        # Python class name. rescan_and_load_plugins re-imports the module, so
        # the loaded class is a distinct (but equivalent) object from this
        # module's own TreeTool import - compare by name/class name, not `is`.
        assert "tree" in PLUGIN_TOOLS.all
        assert PLUGIN_TOOLS.owners["tree"] in config.plugins
        loaded = PLUGIN_TOOLS.all["tree"]
        assert loaded.__name__ == TreeTool.__name__
        assert loaded.tool_name() == "tree"


# `tree`'s own behavior (declined/accepted/inspect flows, metadata listing
# contents) is covered by tests/plugins/test_tree.py, which calls the plain
# tree() function directly - no need to duplicate that here.
