"""Unit tests for `schema/toolset.py` - `HookRunner`'s `@before`/`@after`
orchestration and `Finalizer`'s `ToolResult` -> `ToolReturn` conversion.

Replaces the old `test_base_tool.py`, which tested `BaseTool.solve()`'s
generic error-wrapping and `PLUGIN_HOOKS.before` exception handling - both
concepts are gone. There's no generic "catch whatever a tool raises and turn
it into an error ToolResult" layer anymore (each tool owns its own
try/except, see `command`'s `ToolResult(issues=[e])` return); and
`HookRunner` doesn't swallow a `@before` hook's exception either - raising
there is documented (`toolset.py` module docstring) to block the call, so it
propagates to pydantic-ai's own retry machinery instead of being converted
to a fake result here.

Establishes the pattern for calling a tool through the real toolset stack in
a unit test: build a `RunContext[SolveigDeps]` by hand (same shape
`system_prompt/__init__.py` uses for schema introspection, but with real
`deps` here since these tests actually invoke tools), then
`get_tools(ctx)` + `call_tool(name, args, ctx, tool)` - no `Agent`/model
required, since nothing here is about LLM tool-selection.
"""

import pytest
from pydantic_ai import RunContext
from pydantic_ai.messages import ToolReturn
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets.abstract import AbstractToolset
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai.usage import RunUsage

from solveig.exceptions import PluginException
from solveig.plugins.hooks import after, before, clear_hooks
from solveig.context import SolveigContext
from solveig.tools.result import Finalizer, ToolResult
from solveig.tools.hook_runner import HookRunner
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio


async def dummy_tool(ctx: SolveigContext, value: str) -> ToolResult:
    """A minimal tool for exercising the hook/finalizer pipeline."""
    return ToolResult(content=f"got: {value}")


def make_ctx(config=DEFAULT_CONFIG) -> SolveigContext:
    deps = SolveigContext(config=config, interface=MockInterface())
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), max_retries=1)


async def call_through(
    toolset: AbstractToolset[SolveigContext],
    ctx: RunContext[SolveigContext],
    name: str = "dummy_tool",
    args: dict | None = None,
):
    tools = await toolset.get_tools(ctx)
    return await toolset.call_tool(name, args or {"value": "x"}, ctx, tools[name])


@pytest.fixture(autouse=True)
def clean_hooks():
    clear_hooks()
    yield
    clear_hooks()


# ---------------------------------------------------------------------------
# HookRunner
# ---------------------------------------------------------------------------


class TestHookRunnerBeforeHooks:
    async def test_before_hook_runs_and_call_proceeds(self):
        calls = []

        @before(tools=(dummy_tool,))
        async def record_call(tool_args, config, interface):
            calls.append(tool_args)

        toolset = HookRunner(FunctionToolset([dummy_tool]))
        ctx = make_ctx(DEFAULT_CONFIG.with_(plugins={"record_call": {}}))
        result = await call_through(toolset, ctx)

        assert calls == [{"value": "x"}]
        assert isinstance(result, ToolResult)
        assert result.content == "got: x"

    async def test_before_hook_raising_blocks_the_call(self):
        @before(tools=(dummy_tool,))
        async def blocking_hook(tool_args, config, interface):
            raise PluginException("blocked")

        toolset = HookRunner(FunctionToolset([dummy_tool]))
        ctx = make_ctx(DEFAULT_CONFIG.with_(plugins={"blocking_hook": {}}))

        with pytest.raises(PluginException, match="blocked"):
            await call_through(toolset, ctx)

    async def test_before_hook_skipped_when_plugin_not_enabled(self):
        calls = []

        @before(tools=(dummy_tool,))
        async def record_call(tool_args, config, interface):
            calls.append(tool_args)

        toolset = HookRunner(FunctionToolset([dummy_tool]))
        ctx = make_ctx(DEFAULT_CONFIG.with_(plugins={}))
        result = await call_through(toolset, ctx)

        assert calls == []
        assert isinstance(result, ToolResult)


class TestHookRunnerAfterHooks:
    async def test_after_hook_rewrites_result(self):
        @after(tools=(dummy_tool,))
        async def rewrite(result, config, interface):
            result.content = result.content.upper()
            return result

        toolset = HookRunner(FunctionToolset([dummy_tool]))
        ctx = make_ctx(DEFAULT_CONFIG.with_(plugins={"rewrite": {}}))
        result = await call_through(toolset, ctx)

        assert result.content == "GOT: X"

    async def test_after_hooks_chain_in_registration_order(self):
        @after(tools=(dummy_tool,))
        async def first(result, config, interface):
            result.content += "-first"
            return result

        @after(tools=(dummy_tool,))
        async def second(result, config, interface):
            result.content += "-second"
            return result

        toolset = HookRunner(FunctionToolset([dummy_tool]))
        ctx = make_ctx(DEFAULT_CONFIG.with_(plugins={"first": {}, "second": {}}))
        result = await call_through(toolset, ctx)

        assert result.content == "got: x-first-second"

    async def test_after_hook_skipped_when_plugin_not_enabled(self):
        @after(tools=(dummy_tool,))
        async def rewrite(result, config, interface):
            result.content = result.content.upper()
            return result

        toolset = HookRunner(FunctionToolset([dummy_tool]))
        ctx = make_ctx(DEFAULT_CONFIG.with_(plugins={}))
        result = await call_through(toolset, ctx)

        assert result.content == "got: x"


# ---------------------------------------------------------------------------
# Finalizer
# ---------------------------------------------------------------------------


class TestFinalizer:
    async def test_wraps_tool_result_into_tool_return(self):
        toolset = Finalizer(FunctionToolset([dummy_tool]))
        result = await call_through(toolset, make_ctx())

        assert isinstance(result, ToolReturn)
        assert result.return_value == "got: x"

    async def test_passes_through_non_tool_result(self):
        async def plain_tool(ctx: SolveigContext, value: str) -> str:
            return f"plain: {value}"

        toolset = Finalizer(FunctionToolset([plain_tool]))
        result = await call_through(toolset, make_ctx(), name="plain_tool")

        assert result == "plain: x"


# ---------------------------------------------------------------------------
# Full stack (production wiring): Finalizer(HookRunner(FunctionToolset(...)))
# ---------------------------------------------------------------------------


class TestFullStack:
    async def test_after_hook_private_data_reaches_tool_return_metadata(self):
        @after(tools=(dummy_tool,))
        async def rewrite(result, config, interface):
            result.private["seen"] = True
            return result

        toolset = Finalizer(HookRunner(FunctionToolset([dummy_tool])))
        ctx = make_ctx(DEFAULT_CONFIG.with_(plugins={"rewrite": {}}))
        result = await call_through(toolset, ctx)

        assert isinstance(result, ToolReturn)
        assert result.return_value == "got: x"
        assert result.metadata == {"seen": True}
