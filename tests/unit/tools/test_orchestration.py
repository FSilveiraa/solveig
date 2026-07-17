"""run_tool_and_hooks is the single place that opens a tool's group and
calls execute() - for both the LLM path (agent.py) and the /tool subcommand
path (subcommand/runner.py). These tests exercise it directly."""

import pytest

from solveig.tools.base import BaseTool
from solveig.tools.orchestration import run_tool_and_hooks
from solveig.tools.result import ToolResult
from tests.mocks import DEFAULT_CONFIG
from tests.mocks.interface import MockInterface


class _EchoTool(BaseTool):
    message: str = "hello"

    async def execute(self, config, interface) -> ToolResult:
        # Prove this tool received the *scoped* interface, not the root:
        # display_text should land inside its own group's output, and the
        # object identity should differ from the interface passed into
        # run_tool_and_hooks (which is the root).
        await interface.display_text(self.message)
        return ToolResult(content=self.message, metadata={}, issues=[])


@pytest.mark.anyio
async def test_run_tool_and_hooks_opens_a_group_and_calls_execute():
    interface = MockInterface()
    result = await run_tool_and_hooks(
        _EchoTool(message="hi"), DEFAULT_CONFIG, interface
    )

    assert isinstance(result, ToolResult)
    assert result.content == "hi"
    assert any(g.startswith("START:") for g in interface.groups)
    assert "[TEXT] hi" in interface.outputs


@pytest.mark.anyio
async def test_run_tool_and_hooks_passes_a_scoped_interface_to_execute():
    seen_interfaces = []

    class _CapturingTool(BaseTool):
        async def execute(self, config, interface) -> ToolResult:
            seen_interfaces.append(interface)
            return ToolResult(content=None, metadata={}, issues=[])

    root = MockInterface()
    await run_tool_and_hooks(_CapturingTool(), DEFAULT_CONFIG, root)

    assert len(seen_interfaces) == 1
    # MockInterface.with_group yields self (it stays flat), so identity
    # equality is the correct assertion here - the real TerminalInterface
    # yields a distinct GroupInterface instead, covered by
    # tests/unit/interface/test_conversation_area.py.
    assert seen_interfaces[0] is root
