"""Tests for the hook plugin registry (`solveig/plugins/hooks/__init__.py`).

Replaces the old exception-based `PLUGIN_HOOKS.before`/`.after` list tests
(`ValidationError`/`SecurityError` stopping a `BaseTool.solve()` call) - that
whole exception-translation layer is gone. Scope is split from
`tests/unit/test_toolset.py`, mirroring the tools-side split between
`test_plugin_tools.py` (registry/discovery) and whatever exercises
`AvailableTools.rebuild()`'s `FilteredToolset`: this file owns registry
mechanics (`before`/`after` registration, `plugin_name` derivation,
`clear_hooks`) and real plugin discovery (`load_and_filter_plugin_hooks` finding
`shellcheck`/`trafilatura`); `test_toolset.py` already owns
`run_tool_and_hooks`'s call-time orchestration (gating, blocking, chaining)
using a synthetic tool, so that isn't retested here against real hooks.

One architectural note worth keeping visible: like plugin tools
(`PLUGIN_TOOLS`, `tools/available.py`'s `is_tool_active`), `BEFORE_HOOKS`/
`AFTER_HOOKS` are never filtered by `config.plugins` at load time -
`load_and_filter_plugin_hooks()` discovers and registers everything unconditionally
(hooks self-register via the decorator at import time), and `config.plugins`
gating happens live, per call, inside `run_tool_and_hooks`
(`tools/orchestration.py`). So "skipped" here only ever means "not reported
as active" (an interface message), never "absent from the registry" - the
same live-filter-over-a-static-registry shape both plugin systems share.
"""

from unittest.mock import patch

import pytest

from solveig.config import SolveigConfig
from solveig.plugins import clear_plugins, discover_plugins
from solveig.plugins.hooks import (
    AFTER_HOOKS,
    BEFORE_HOOKS,
    after,
    before,
    clear_hooks,
    load_and_filter_plugin_hooks,
    plugin_name,
    registered_plugin_names,
)
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def clean_hooks():
    clear_hooks()
    yield
    clear_hooks()


# ---------------------------------------------------------------------------
# @before / @after registration mechanics
# ---------------------------------------------------------------------------


class TestHookRegistration:
    async def test_before_registers_under_tool_name(self):
        async def my_hook(tool_args, config, interface): ...

        hook = before(tools=("some_tool",))(my_hook)

        assert BEFORE_HOOKS["some_tool"] == [hook]
        assert hook.fn is my_hook

    async def test_before_registers_under_function_target(self):
        async def target_tool(ctx): ...

        async def my_hook(tool_args, config, interface): ...

        hook = before(tools=(target_tool,))(my_hook)

        assert BEFORE_HOOKS["target_tool"] == [hook]
        assert hook.fn is my_hook

    async def test_after_registers_under_tool_name(self):
        async def my_hook(result, config, interface):
            return result

        hook = after(tools=("some_tool",))(my_hook)

        assert AFTER_HOOKS["some_tool"] == [hook]
        assert hook.fn is my_hook

    async def test_hook_registers_under_multiple_targets(self):
        async def my_hook(tool_args, config, interface): ...

        hook = before(tools=("tool_a", "tool_b"))(my_hook)

        assert BEFORE_HOOKS["tool_a"] == [hook]
        assert BEFORE_HOOKS["tool_b"] == [hook]
        assert hook.fn is my_hook

    async def test_clear_hooks_empties_both_registries(self):
        async def my_before(tool_args, config, interface): ...

        async def my_after(result, config, interface):
            return result

        before(tools=("some_tool",))(my_before)
        after(tools=("some_tool",))(my_after)

        clear_hooks()

        assert BEFORE_HOOKS == {}
        assert AFTER_HOOKS == {}

    async def test_registered_plugin_names_covers_before_and_after(self):
        async def before_hook(tool_args, config, interface): ...

        async def after_hook(result, config, interface):
            return result

        before(tools=("some_tool",))(before_hook)
        after(tools=("some_tool",))(after_hook)

        # Neither function lives under a `.hooks.` module path (they're
        # defined inline here), so plugin_name() falls back to the
        # function's own __name__.
        assert registered_plugin_names() == {"before_hook", "after_hook"}


# ---------------------------------------------------------------------------
# plugin_name() derivation
# ---------------------------------------------------------------------------


class TestPluginNameDerivation:
    async def test_derives_name_from_hooks_module_path(self):
        from solveig.plugins.hooks.shellcheck import shellcheck

        assert plugin_name(shellcheck) == "shellcheck"

    @pytest.mark.no_file_mocking
    async def test_derives_name_from_hooks_module_path_for_after_hook(self):
        # trafilatura reads its own settings.cfg on import.
        from solveig.plugins.hooks.trafilatura import trafilatura

        assert plugin_name(trafilatura) == "trafilatura"

    async def test_falls_back_to_function_name_outside_hooks_package(self):
        async def a_locally_defined_hook(tool_args, config, interface): ...

        # plugin_name() expects a Hook object; wrap the local function so
        # the test exercises the fallback-to-__name__ path.
        from solveig.plugins.hooks import Hook
        h = Hook(a_locally_defined_hook)
        assert plugin_name(h) == "a_locally_defined_hook"


# ---------------------------------------------------------------------------
# load_and_filter_plugin_hooks() - discovery and reporting
# ---------------------------------------------------------------------------


class TestLoadAndFilterHooks:
    async def test_hook_registered_regardless_of_config(self):
        """Discovery/registration is unconditional — hooks self-register at import,
        and load_and_filter_plugin_hooks just rescans + returns errors."""
        async def my_hook(tool_args, config, interface): ...

        def fake_rescan(path):
            before(tools=("some_tool",))(my_hook)
            return (1, 0, [])  # succeeded, failed, errors

        config = SolveigConfig(cli_args=[], api={"url":"http://x","key":"k"})
        with patch(
            "solveig.plugins.hooks.rescan_and_load_plugins", side_effect=fake_rescan
        ):
            errors = load_and_filter_plugin_hooks(config)

        assert errors == []  # no import errors
        assert len(BEFORE_HOOKS["some_tool"]) == 1
        assert BEFORE_HOOKS["some_tool"][0].fn is my_hook

    async def test_reports_loaded_when_plugin_in_config(self):
        async def my_hook(tool_args, config, interface): ...

        def fake_rescan(path):
            before(tools=("some_tool",))(my_hook)
            return (1, 0, [])

        config = SolveigConfig(
            cli_args=[], api={"url":"http://x","key":"k"},
            plugins={"hooks": {"my_hook": {}}},
        )
        with patch(
            "solveig.plugins.hooks.rescan_and_load_plugins", side_effect=fake_rescan
        ):
            errors = load_and_filter_plugin_hooks(config)

        # Registration is unconditional; gating is live in run_tool_and_hooks.
        assert errors == []
        assert BEFORE_HOOKS["some_tool"][0].fn is my_hook

    async def test_reports_skipped_when_plugin_not_in_config(self):
        async def my_hook(tool_args, config, interface): ...

        def fake_rescan(path):
            before(tools=("some_tool",))(my_hook)
            return (1, 0, [])

        config = SolveigConfig(cli_args=[], api={"url":"http://x","key":"k"})
        with patch(
            "solveig.plugins.hooks.rescan_and_load_plugins", side_effect=fake_rescan
        ):
            errors = load_and_filter_plugin_hooks(config)

        # Registration is always unconditional — hooks register regardless.
        assert errors == []
        assert BEFORE_HOOKS["some_tool"][0].fn is my_hook

    @pytest.mark.no_file_mocking
    async def test_shellcheck_and_trafilatura_discovered_via_real_scan(self):
        """Real hook plugins self-register on discovery, independent of config.plugins."""
        SolveigConfig.compose_core_tools()
        config = SolveigConfig(
            cli_args=[],
            api={"url": "test-url", "key": "test-key"},
            plugins={"some_other_plugin": {}},
        )
        load_and_filter_plugin_hooks(config=config)

        before_names = {plugin_name(hook) for hook in BEFORE_HOOKS.get("command", [])}
        after_names = {plugin_name(hook) for hook in AFTER_HOOKS.get("http", [])}
        assert "shellcheck" in before_names
        assert "trafilatura" in after_names

    @pytest.mark.no_file_mocking
    async def test_no_duplicate_registration_across_repeated_loads(self, load_plugins):
        """Reloading plugin modules on repeated loads doesn't grow the registry unboundedly."""
        SolveigConfig.compose_core_tools()
        config = SolveigConfig(
            cli_args=[], api={"url": "test-url", "key": "test-key"}, plugins={"shellcheck": {}}
        )

        def command_hook_count() -> int:
            return len(BEFORE_HOOKS.get("command", []))

        await load_plugins(config)
        count_after_first = command_hook_count()

        await load_plugins(config)
        await load_plugins(config)

        assert count_after_first > 0
        assert command_hook_count() == count_after_first

        clear_plugins()


# ---------------------------------------------------------------------------
# discover_plugins() - full plugin bootstrap
# ---------------------------------------------------------------------------


class TestInitializePlugins:
    @pytest.mark.no_file_mocking
    async def test_hooks_registered_even_when_owning_plugin_not_enabled(self):
        """discover_plugins() discovers every hook plugin, active or not."""
        SolveigConfig.compose_core_tools()
        config = SolveigConfig(
            cli_args=[],
            api={"url": "test-url", "key": "test-key"},
            plugins={"some_other_plugin": {}},
        )
        discover_plugins(config=config)

        before_names = {plugin_name(hook) for hook in BEFORE_HOOKS.get("command", [])}
        assert "shellcheck" in before_names

        clear_plugins()
