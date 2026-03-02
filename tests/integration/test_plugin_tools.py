"""Tests for the tool plugin system."""

from unittest.mock import MagicMock, patch

import pytest

from solveig.config import SolveigConfig
from solveig.plugins.tools import PLUGIN_TOOLS, load_and_filter_tools
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Tool plugin filtering
# ---------------------------------------------------------------------------


class TestToolPluginFiltering:
    @pytest.fixture(autouse=True)
    def clean_tools(self):
        PLUGIN_TOOLS.clear()

    async def test_tool_enabled_when_in_config(self):
        """Tools in config.plugins are moved into active after loading."""
        mock_tool_cls = MagicMock()

        async def fake_rescan(**_):
            PLUGIN_TOOLS.all["my_tool"] = mock_tool_cls

        config = DEFAULT_CONFIG.with_(plugins={"my_tool": {}})
        with patch(
            "solveig.plugins.tools.rescan_and_load_plugins", side_effect=fake_rescan
        ):
            await load_and_filter_tools(config, MockInterface())

        assert PLUGIN_TOOLS.active["my_tool"] is mock_tool_cls

    async def test_tool_disabled_when_not_in_config(self):
        """Tools absent from config.plugins are not moved into active."""
        mock_tool_cls = MagicMock()

        async def fake_rescan(**_):
            PLUGIN_TOOLS.all["my_tool"] = mock_tool_cls

        config = DEFAULT_CONFIG.with_(plugins={})
        with patch(
            "solveig.plugins.tools.rescan_and_load_plugins", side_effect=fake_rescan
        ):
            await load_and_filter_tools(config, MockInterface())

        assert "my_tool" not in PLUGIN_TOOLS.active

    async def test_tree_plugin_skipped_when_not_in_config(self):
        """The real tree plugin is not activated when absent from config.plugins."""
        config = SolveigConfig(
            url="test-url",
            api_key="test-key",
            plugins={"some_other_plugin": {}},
        )
        await load_and_filter_tools(config=config, interface=MockInterface())

        assert "tree" not in PLUGIN_TOOLS.active

    async def test_tree_plugin_loaded_when_in_config(self):
        """The real tree plugin is activated when listed in config.plugins."""
        config = SolveigConfig(
            url="test-url",
            api_key="test-key",
            plugins={"tree": {}},
        )
        await load_and_filter_tools(config=config, interface=MockInterface())

        # importlib.reload() produces a fresh class object, so check by name not identity
        assert "tree" in PLUGIN_TOOLS.active
        assert PLUGIN_TOOLS.active["tree"].__name__ == "TreeTool"


# ---------------------------------------------------------------------------
# TreeTool behaviour
# ---------------------------------------------------------------------------


@pytest.mark.no_file_mocking
class TestTreeTool:
    async def test_declined_returns_non_accepted_result(self, tmp_path):
        """User choosing 'Don't read anything' returns accepted=False with no error."""
        from solveig.plugins.tools.tree import TreeTool

        result = await TreeTool(path=str(tmp_path), comment="Test").solve(
            DEFAULT_CONFIG.with_(), MockInterface(choices=[2])
        )

        assert not result.accepted
        assert result.error is None

    async def test_read_and_send_returns_accepted_result_with_metadata(self, tmp_path):
        """User choosing 'Read and send tree' returns accepted=True with metadata."""
        from solveig.plugins.tools.tree import TreeResult, TreeTool

        (tmp_path / "file.txt").write_text("hello")
        (tmp_path / "subdir").mkdir()

        result = await TreeTool(path=str(tmp_path), comment="Test").solve(
            DEFAULT_CONFIG.with_(), MockInterface(choices=[0])
        )

        assert isinstance(result, TreeResult)
        assert result.accepted
        assert result.metadata is not None

    async def test_inspect_first_then_send(self, tmp_path):
        """User inspects tree then approves sending it."""
        from solveig.plugins.tools.tree import TreeTool

        result = await TreeTool(path=str(tmp_path), comment="Test").solve(
            DEFAULT_CONFIG.with_(),
            MockInterface(choices=[1, 0]),  # inspect, then Yes
        )

        assert result.accepted

    async def test_inspect_first_then_decline(self, tmp_path):
        """User inspects tree then declines sending it."""
        from solveig.plugins.tools.tree import TreeTool

        result = await TreeTool(path=str(tmp_path), comment="Test").solve(
            DEFAULT_CONFIG.with_(),
            MockInterface(choices=[1, 1]),  # inspect, then No
        )

        assert not result.accepted

    async def test_metadata_listing_contains_created_files(self, tmp_path):
        """Tree result metadata listing includes the files that actually exist."""
        from solveig.plugins.tools.tree import TreeTool

        (tmp_path / "alpha.txt").write_text("a")
        (tmp_path / "beta.txt").write_text("b")
        (tmp_path / "subdir").mkdir()

        result = await TreeTool(path=str(tmp_path), comment="Test").solve(
            DEFAULT_CONFIG.with_(), MockInterface(choices=[0])
        )

        assert result.accepted
        # listing is keyed by absolute path; extract basenames for assertion
        listing = result.metadata.listing or {}
        names = {p.rsplit("/", 1)[-1] for p in listing}
        assert "alpha.txt" in names
        assert "beta.txt" in names
        assert "subdir" in names
