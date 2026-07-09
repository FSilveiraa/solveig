"""Tests for the shellcheck hook plugin (`solveig/plugins/hooks/shellcheck.py`).

`shellcheck` is a plain `@before(tools=(command,))`-decorated function now -
no `PLUGIN_HOOKS.before` list, no `CommandTool`/`ReadTool` Pydantic models.
Raising from it (`SecurityError`/`ValidationError`) blocks the call, per
`HookRunner`'s contract (`schema/toolset.py`) - there's no result object to
inspect for "was this blocked", just `pytest.raises(...)`.

Three layers of coverage, matching the split established in
`test_plugin_hooks.py`/`test_toolset.py`: calling the hook function
directly (business logic - dangerous-pattern detection, shellcheck output
parsing), registry/discovery (does it register on `command` and nowhere
else), and one full-stack test through the real `HookRunner` proving it
actually blocks a real `command()` call end to end.
"""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai.usage import RunUsage

from solveig.exceptions import SecurityError, ValidationError
from solveig.plugins.hooks import (
    BEFORE_HOOKS,
    clear_hooks,
    load_and_filter_hooks,
    plugin_name,
)
from solveig.plugins.hooks.shellcheck import is_obviously_dangerous, shellcheck
from solveig.schema.deps import SolveigContext, SolveigDeps
from solveig.schema.tools.core.command import command
from solveig.schema.toolset import HookRunner
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio

SHELLCHECK_CONFIG = DEFAULT_CONFIG.with_(plugins={"shellcheck": {}})


def make_ctx(config=DEFAULT_CONFIG, interface=None) -> SolveigContext:
    deps = SolveigDeps(config=config, interface=interface or MockInterface())
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), max_retries=1)


class TestDangerousPatternDetection:
    async def test_detects_dangerous_commands(self):
        for cmd in ["rm -rf /", "rm -rf /*", "mkfs.ext4 /dev/sda1", ":(){:|:&};:"]:
            assert is_obviously_dangerous(cmd), f"Should detect '{cmd}' as dangerous"

    async def test_allows_safe_commands(self):
        for cmd in [
            "ls -la",
            "echo hello world",
            "mkdir test_directory",
            "rm file.txt",
        ]:
            assert not is_obviously_dangerous(cmd), (
                f"Should not detect '{cmd}' as dangerous"
            )


class TestShellcheckHookDirect:
    """Calling the hook function directly - no toolset/registry involved."""

    async def test_dangerous_pattern_raises_security_error(self, tmp_path):
        interface = MockInterface()

        with pytest.raises(SecurityError, match="dangerous pattern") as exc_info:
            await shellcheck(
                {"command": f"mkfs.ext4 {tmp_path}/__non-existent-path__/sdx1"},
                SHELLCHECK_CONFIG,
                interface,
            )
        assert "mkfs.ext4" in str(exc_info.value)

    @pytest.mark.no_subprocess_mocking
    async def test_valid_command_passes_without_raising(self):
        """Runs the real `shellcheck` binary - skipped/failing if it's not installed."""
        interface = MockInterface()

        await shellcheck(
            {"command": "echo 'hello world'"}, SHELLCHECK_CONFIG, interface
        )

        assert "no issues" in interface.get_all_output().lower()

    @pytest.mark.no_subprocess_mocking
    async def test_invalid_syntax_declined_raises_validation_error(self):
        interface = MockInterface(choices=[1])  # decline to execute anyway

        with pytest.raises(ValidationError, match="Execution cancelled"):
            await shellcheck(
                {"command": "if then\n  echo 'broken'\nfi"},
                SHELLCHECK_CONFIG,
                interface,
            )

        assert "couldn't parse this if expression" in interface.get_all_output().lower()

    @pytest.mark.no_subprocess_mocking
    async def test_invalid_syntax_run_anyway_does_not_raise(self):
        interface = MockInterface(choices=[0])  # execute anyway

        await shellcheck(
            {"command": "if then\n  echo 'broken'\nfi"},
            SHELLCHECK_CONFIG,
            interface,
        )

    async def test_shellcheck_not_available_warns_but_does_not_raise(self):
        interface = MockInterface()

        with patch(
            "asyncio.create_subprocess_shell", new_callable=AsyncMock
        ) as mock_create_subprocess_shell:
            mock_process = AsyncMock()
            mock_process.returncode = 127
            mock_process.communicate.return_value = (
                b"",
                b"/bin/sh: shellcheck: command not found",
            )
            mock_create_subprocess_shell.return_value = mock_process

            await shellcheck({"command": "echo test"}, SHELLCHECK_CONFIG, interface)

        output = interface.get_all_output().lower()
        assert "warning" in output
        assert "shellcheck plugin is enabled" in output
        assert "command is not available." in output


class TestShellcheckDiscoveryAndRegistration:
    @pytest.fixture(autouse=True)
    def clean_hooks(self):
        clear_hooks()
        yield
        clear_hooks()

    async def test_registers_as_a_before_hook_on_command(self):
        await load_and_filter_hooks(SHELLCHECK_CONFIG, MockInterface())

        hook_names = [plugin_name(hook) for hook in BEFORE_HOOKS.get("command", [])]
        assert "shellcheck" in hook_names

    async def test_does_not_register_for_other_tools(self):
        await load_and_filter_hooks(SHELLCHECK_CONFIG, MockInterface())

        for tool_name, hooks in BEFORE_HOOKS.items():
            if tool_name != "command":
                assert not any(plugin_name(hook) == "shellcheck" for hook in hooks)


class TestShellcheckBlocksCommandThroughHookRunner:
    """Full stack: real registry + real `HookRunner`, proving shellcheck
    actually blocks a real `command()` call when wired in - not just the
    hook function in isolation."""

    @pytest.fixture(autouse=True)
    def clean_hooks(self):
        clear_hooks()
        yield
        clear_hooks()

    @pytest.mark.no_subprocess_mocking
    async def test_dangerous_command_blocked(self):
        await load_and_filter_hooks(SHELLCHECK_CONFIG, MockInterface())
        toolset = HookRunner(FunctionToolset([command]))
        ctx = make_ctx(SHELLCHECK_CONFIG, MockInterface())

        tools = await toolset.get_tools(ctx)
        with pytest.raises(SecurityError):
            await toolset.call_tool(
                "command", {"command": "rm -rf /"}, ctx, tools["command"]
            )

    @pytest.mark.no_subprocess_mocking
    async def test_read_is_never_gated_by_shellcheck(self, tmp_path):
        """shellcheck only registered on `command` - a `read` call never
        even consults it, regardless of what's in the registry."""
        from solveig.schema.tools.core.read import read
        from solveig.schema.tools.result import ToolResult

        await load_and_filter_hooks(SHELLCHECK_CONFIG, MockInterface())
        toolset = HookRunner(FunctionToolset([read]))
        interface = MockInterface(choices=[1])  # decline to send metadata
        ctx = make_ctx(SHELLCHECK_CONFIG, interface)

        tools = await toolset.get_tools(ctx)
        result = await toolset.call_tool(
            "read",
            {"path": str(tmp_path), "metadata_only": True},
            ctx,
            tools["read"],
        )

        assert isinstance(result, ToolResult)
        assert result.content == "User declined to send metadata."
