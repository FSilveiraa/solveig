"""Tests for the hook plugin registry (`solveig/plugins/hooks.py`).

Replaces the old exception-based `PLUGIN_HOOKS.before`/`.after` list tests
(`ValidationError`/`SecurityError` stopping a `BaseTool.solve()` call) - that
whole exception-translation layer is gone. Scope is split from
`tests/unit/test_toolset.py`, mirroring the tools-side split between
`test_plugin_tools.py` (registry/discovery) and whatever exercises
`AvailableTools.rebuild()`'s `FilteredToolset`: this file owns registry
mechanics (`before`/`after` registration, `hook_name`, `clear_hooks`) and real
plugin discovery (`discover_plugins` finding `shellcheck`/`trafilatura`); `test_toolset.py` already owns
`run_tool_and_hooks`'s call-time orchestration (gating, blocking, chaining)
using a synthetic tool, so that isn't retested here against real hooks.

One architectural note worth keeping visible: like plugin tools
(`PLUGIN_TOOLS`, `tools/available.py`'s `is_tool_active`), `HOOKS` entries
are never filtered by `config.plugins` at load time -
`discover_plugins()` discovers and registers everything unconditionally
(hooks self-register via the decorator at import time), and `config.plugins`
gating happens live, per call, inside `run_tool_and_hooks`
(`tools/orchestration.py`). So "skipped" here only ever means "not reported
as active" (an interface message), never "absent from the registry" - the
same live-filter-over-a-static-registry shape both plugin systems share.
"""

from unittest.mock import patch

import pytest

from solveig import bootstrap
from solveig.config import SolveigConfig
from solveig.plugins.discovery import clear_plugins, discover_plugins
from solveig.plugins.hooks import (
    HOOKS,
    HookKind,
    hooks_for,
    after_tool,
    before_tool,
    clear_hooks,
    hook_name,
)
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def clean_hooks():
    clear_hooks()
    yield
    clear_hooks()


# ---------------------------------------------------------------------------
# @before_tool / @after_tool registration mechanics
# ---------------------------------------------------------------------------


class TestHookRegistration:
    async def test_before_registers_under_tool_name(self):
        async def my_hook(tool_args, config, interface): ...

        hook = before_tool(tools=("some_tool",))(my_hook)

        assert hooks_for(HookKind.BEFORE_TOOL, "some_tool") == [hook]
        assert hook.fn is my_hook

    async def test_before_registers_under_function_target(self):
        async def target_tool(ctx): ...

        async def my_hook(tool_args, config, interface): ...

        hook = before_tool(tools=(target_tool,))(my_hook)

        assert hooks_for(HookKind.BEFORE_TOOL, "target_tool") == [hook]
        assert hook.fn is my_hook

    async def test_after_registers_under_tool_name(self):
        async def my_hook(result, config, interface):
            return result

        hook = after_tool(tools=("some_tool",))(my_hook)

        assert hooks_for(HookKind.AFTER_TOOL, "some_tool") == [hook]
        assert hook.fn is my_hook

    async def test_hook_registers_under_multiple_targets(self):
        async def my_hook(tool_args, config, interface): ...

        hook = before_tool(tools=("tool_a", "tool_b"))(my_hook)

        assert hooks_for(HookKind.BEFORE_TOOL, "tool_a") == [hook]
        assert hooks_for(HookKind.BEFORE_TOOL, "tool_b") == [hook]
        assert hook.fn is my_hook

    async def test_clear_hooks_empties_every_kind(self):
        async def my_before(tool_args, config, interface): ...

        async def my_after(result, config, interface):
            return result

        before_tool(tools=("some_tool",))(my_before)
        after_tool(tools=("some_tool",))(my_after)

        clear_hooks()

        assert HOOKS == {}
        assert hooks_for(HookKind.BEFORE_TOOL, "some_tool") == []
        assert hooks_for(HookKind.AFTER_TOOL, "some_tool") == []

# ---------------------------------------------------------------------------
# discover_plugins() - discovery and reporting
# ---------------------------------------------------------------------------


class TestLoadAndFilterHooks:
    async def test_hook_registered_regardless_of_config(self):
        """Discovery/registration is unconditional — hooks self-register at import,
        and discover_plugins just rescans + returns errors."""
        async def my_hook(tool_args, config, interface): ...

        def fake_rescan(path):
            before_tool(tools=("some_tool",))(my_hook)
            return (1, 0, [])  # succeeded, failed, errors

        config = SolveigConfig(cli_args=[], api={"url":"http://x","key":"k"})
        with patch(
            "solveig.plugins.discovery.rescan_and_load_plugins", side_effect=fake_rescan
        ):
            errors = discover_plugins([])

        assert errors == []  # no import errors
        assert len(hooks_for(HookKind.BEFORE_TOOL, "some_tool")) == 1
        assert hooks_for(HookKind.BEFORE_TOOL, "some_tool")[0].fn is my_hook

    async def test_reports_loaded_when_plugin_in_config(self):
        async def my_hook(tool_args, config, interface): ...

        def fake_rescan(path):
            before_tool(tools=("some_tool",))(my_hook)
            return (1, 0, [])

        config = SolveigConfig(
            cli_args=[], api={"url":"http://x","key":"k"},
            plugins={"hooks": {"my_hook": {}}},
        )
        with patch(
            "solveig.plugins.discovery.rescan_and_load_plugins", side_effect=fake_rescan
        ):
            errors = discover_plugins([])

        # Registration is unconditional; gating is live in run_tool_and_hooks.
        assert errors == []
        assert hooks_for(HookKind.BEFORE_TOOL, "some_tool")[0].fn is my_hook

    async def test_reports_skipped_when_plugin_not_in_config(self):
        async def my_hook(tool_args, config, interface): ...

        def fake_rescan(path):
            before_tool(tools=("some_tool",))(my_hook)
            return (1, 0, [])

        config = SolveigConfig(cli_args=[], api={"url":"http://x","key":"k"})
        with patch(
            "solveig.plugins.discovery.rescan_and_load_plugins", side_effect=fake_rescan
        ):
            errors = discover_plugins([])

        # Registration is always unconditional — hooks register regardless.
        assert errors == []
        assert hooks_for(HookKind.BEFORE_TOOL, "some_tool")[0].fn is my_hook

    @pytest.mark.no_file_mocking
    async def test_shellcheck_and_trafilatura_discovered_via_real_scan(self):
        """Real hook plugins self-register on discovery, independent of config.plugins."""
        bootstrap.compose_core_tools()
        config = SolveigConfig(
            cli_args=[],
            api={"url": "test-url", "key": "test-key"},
            plugins={"some_other_plugin": {}},
        )
        discover_plugins([])

        before_names = {hook_name(hook) for hook in hooks_for(HookKind.BEFORE_TOOL, "command")}
        after_names = {hook_name(hook) for hook in hooks_for(HookKind.AFTER_TOOL, "http")}
        assert "shellcheck" in before_names
        assert "trafilatura" in after_names

    @pytest.mark.no_file_mocking
    async def test_no_duplicate_registration_across_repeated_loads(self, load_plugins):
        """Reloading plugin modules on repeated loads doesn't grow the registry unboundedly."""
        bootstrap.compose_core_tools()
        config = SolveigConfig(
            cli_args=[], api={"url": "test-url", "key": "test-key"}, plugins={"shellcheck": {}}
        )

        def command_hook_count() -> int:
            return len(hooks_for(HookKind.BEFORE_TOOL, "command"))

        await load_plugins()
        count_after_first = command_hook_count()

        await load_plugins()
        await load_plugins()

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
        bootstrap.compose_core_tools()
        config = SolveigConfig(
            cli_args=[],
            api={"url": "test-url", "key": "test-key"},
            plugins={"some_other_plugin": {}},
        )
        discover_plugins([])

        before_names = {hook_name(hook) for hook in hooks_for(HookKind.BEFORE_TOOL, "command")}
        assert "shellcheck" in before_names

        clear_plugins()
