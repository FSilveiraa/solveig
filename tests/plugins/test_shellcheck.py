"""Tests for the shellcheck hook plugin (`solveig/plugins/library/shellcheck.py`).

`shellcheck` is a plain `@before_tool(tools=(CommandTool,))`-decorated function -
registered under `CommandTool.tool_name()` ("command") in the `HOOKS`
registry (`solveig/plugins/hooks.py`). Raising from it
(`SecurityError`/`ValidationError`) blocks the call - there's no result
object to inspect for "was this blocked", just `pytest.raises(...)`.

Three layers of coverage: calling the hook function directly (business
logic - dangerous-pattern detection, shellcheck output parsing), registry/
discovery (does it register on `command` and nowhere else), and one
full-stack test through the real `run_tool_and_hooks` (the shared
orchestration seam both the Agent path and the `/tool` subcommand path run
through - see `tools/orchestration.py`), proving shellcheck actually blocks
a real `CommandTool` call end to end, not just the hook function in isolation.
"""

from unittest.mock import AsyncMock, patch

import pytest

from solveig import bootstrap
from solveig.config import SolveigConfig
from solveig.exceptions import SecurityError, ValidationError
from solveig.plugins.discovery import discover_plugins
from solveig.plugins.hooks import HOOKS, HookKind, clear_hooks, hook_name, hooks_for
from solveig.plugins.library.shellcheck import is_obviously_dangerous, shellcheck
from solveig.tools.core.command import CommandTool
from solveig.tools.orchestration import run_tool_and_hooks
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio

import shutil
_needs_shellcheck = pytest.mark.skipif(
    shutil.which("shellcheck") is None,
    reason="shellcheck binary not installed",
)


@pytest.fixture(autouse=True, scope="module")
def _compose_and_build_config():
    """Discover plugins and make SHELLCHECK_CONFIG available.

    One call, not discover-then-compose: the schema recomposes as a reaction to
    the scan, so a test cannot end up with shellcheck registered but absent from
    `config.plugins.hooks` - which used to hand back a raw dict and fail as an
    AttributeError inside the hook body."""
    global SHELLCHECK_CONFIG
    bootstrap.compose_core_tools()
    discover_plugins([])
    SHELLCHECK_CONFIG = SolveigConfig(
        cli_args=[],
        api={"url": "http://x", "key": "k"},
        plugins={"hooks": {"shellcheck": {}}},
    )


SHELLCHECK_CONFIG: SolveigConfig  # set by fixture above


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


@_needs_shellcheck
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
        discover_plugins([])

        hook_names = [hook_name(hook) for hook in hooks_for(HookKind.BEFORE_TOOL, "command")]
        assert "shellcheck" in hook_names

    async def test_does_not_register_for_other_tools(self):
        discover_plugins([])

        for tool_name, hooks in HOOKS[HookKind.BEFORE_TOOL].items():  # noqa
            if tool_name != "command":
                assert not any(hook_name(hook) == "shellcheck" for hook in hooks)


@_needs_shellcheck
class TestShellcheckBlocksCommandThroughOrchestration:
    """Full stack: real registry + the real `run_tool_and_hooks` seam, proving
    shellcheck actually blocks a real `CommandTool` call when wired in - not
    just the hook function in isolation. This is the same seam both the
    LLM tool-call path and the `/tool` subcommand path run through."""

    @pytest.fixture(autouse=True)
    def clean_hooks(self):
        clear_hooks()
        yield
        clear_hooks()

    @pytest.mark.no_subprocess_mocking
    async def test_dangerous_command_blocked(self):
        discover_plugins([])
        interface = MockInterface()
        instance = CommandTool(command="rm -rf /")

        with pytest.raises(SecurityError):
            await run_tool_and_hooks(
                instance,
                SHELLCHECK_CONFIG,
                interface,
            )

    @pytest.mark.no_subprocess_mocking
    @pytest.mark.no_file_mocking
    async def test_read_is_never_gated_by_shellcheck(self, tmp_path):
        """shellcheck only registered on `command` - a `read` call never
        even consults it, regardless of what's in the registry."""
        from solveig.tools.core.read import ReadTool

        discover_plugins([])
        interface = MockInterface(choices=[1])  # decline to send metadata
        instance = ReadTool(path=str(tmp_path), metadata_only=True)

        result = await run_tool_and_hooks(
            instance,
            SHELLCHECK_CONFIG,
            interface,
        )

        assert result.content == "User declined to send metadata."
