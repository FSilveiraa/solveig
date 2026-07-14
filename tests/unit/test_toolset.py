"""Tier-2 plumbing tests for the tool bridge + tool-execution capability.

These drive the *framework* surface the migration introduced, not tool bodies:
`BaseTool.as_tool()` flattening/schema, and `build_tool_execution_capability`
running the plugin `@before`/`@after` hooks and rendering a `ToolResult` into
the `ToolReturn` the model sees. They couple to pydantic-ai's schema/message
layer on purpose - they're the early-warning system for a framework change
that breaks the bridge.
"""

import warnings

import pytest
from pydantic import Field
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets.abstract import AbstractToolset
from pydantic_ai.toolsets.function import FunctionToolset

from solveig.agent import build_tool_execution_capability
from solveig.context import SolveigContext
from solveig.exceptions import PluginException
from solveig.plugins.hooks import after, before, clear_hooks
from solveig.tools.available import tool_classes
from solveig.tools.base import BaseTool
from solveig.tools.core.edit import EditTool
from solveig.tools.result import ToolResult
from tests.mocks import DEFAULT_CONFIG, MockInterface, create_mock_model

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _clean_hooks():
    """Hooks register into module-global registries; drop any a test added so
    it can't leak into later tests."""
    yield
    clear_hooks()


async def drive_tool_call(
    toolset: AbstractToolset,
    call: ToolCallPart,
    *,
    config=DEFAULT_CONFIG,
    interface=None,
    capabilities=None,
):
    """Run one scripted tool call through a real `Agent`: the model emits `call`,
    then a final text part to end the run. Returns the `AgentRunResult` so the
    test can inspect `all_messages()`. Ceremony (FunctionModel scripting, deps)
    lives here so the plumbing tests stay about *what* the framework did."""
    interface = interface or MockInterface()
    model = create_mock_model(
        ModelResponse(parts=[call]),
        ModelResponse(parts=[TextPart(content="done")]),
    )
    agent = Agent(
        model,
        deps_type=SolveigContext,
        toolsets=[toolset],
        capabilities=capabilities or [],
    )
    return await agent.run(
        "go", deps=SolveigContext(config=config, interface=interface)
    )


def _tool_returns(result) -> list[ToolReturnPart]:
    return [
        part
        for message in result.all_messages()
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolReturnPart)
    ]


def _retries(result) -> list[RetryPromptPart]:
    return [
        part
        for message in result.all_messages()
        for part in getattr(message, "parts", [])
        if isinstance(part, RetryPromptPart)
    ]


class EchoTool(BaseTool):
    """Echo the given value back (test-only tool)."""

    value: str = Field(description="text to echo")

    async def execute(self, ctx) -> ToolResult:  # type: ignore[no-untyped-def]
        return ToolResult(
            content=f"echoed: {self.value}", private={"secret": self.value}
        )


def _echo_call(value: str = "hi", call_id: str = "c1") -> ToolCallPart:
    return ToolCallPart(tool_name="echo", args={"value": value}, tool_call_id=call_id)


# ---------------------------------------------------------------------------
# as_tool() bridge: schema cleanliness + flattening
# ---------------------------------------------------------------------------


async def test_building_toolset_emits_no_return_schema_warning():
    """`as_tool()` annotates its return as `ToolReturn`, not the `ToolResult`
    dataclass - otherwise pydantic-ai can't build a return schema and warns
    once per tool per build. Guards that regression (there's no
    `filterwarnings` config catching it otherwise)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        FunctionToolset([cls.as_tool() for cls in tool_classes().values()])
    offending = [
        str(w.message)
        for w in caught
        if "Could not generate return schema" in str(w.message)
    ]
    assert offending == [], offending


async def test_as_tool_flattens_model_fields():
    """The load-bearing bridge: a tool's model fields must present as *flat*
    top-level tool arguments (single-model-parameter flattening), not a single
    nested `params` object. A pydantic-ai change that broke this would collapse
    every tool's schema - this pins it."""
    toolset = FunctionToolset([EditTool.as_tool()])
    model = TestModel(call_tools=[])  # returns text, never calls the tool
    agent = Agent(model, deps_type=SolveigContext, toolsets=[toolset])

    await agent.run("hi", deps=SolveigContext(config=None, interface=None))  # type: ignore[arg-type]

    tool_defs = model.last_model_request_parameters.function_tools
    edit_def = next(t for t in tool_defs if t.name == "edit")
    params = edit_def.parameters_json_schema.get("properties", {})
    assert {"path", "old_string", "new_string", "replace_all"} <= set(params)
    assert "params" not in params  # not nested under a single model param


# ---------------------------------------------------------------------------
# build_tool_execution_capability: result rendering + hooks + retries
# ---------------------------------------------------------------------------


async def test_capability_renders_tool_result_to_tool_return():
    """`content` (assistant text) -> `return_value`, and `private` -> `metadata`
    (kept in history, never shown to the model). Drives the real capability."""
    result = await drive_tool_call(
        FunctionToolset([EchoTool.as_tool()]),
        _echo_call(),
        capabilities=[build_tool_execution_capability()],
    )

    returns = _tool_returns(result)
    assert len(returns) == 1
    assert returns[0].content == "echoed: hi"
    assert returns[0].metadata == {"secret": "hi"}


async def test_before_and_after_hooks_fire_and_are_gated_by_config_plugins():
    """`@before` runs before the body, `@after` can transform the result - but
    only when the hook's plugin is enabled in `config.plugins` (gated live, per
    call). Off -> body result passes through untouched; on -> both fire."""
    fired: list[str] = []

    @before((EchoTool,))
    async def record_before(args, config, interface):
        fired.append("before")

    @after((EchoTool,))
    async def transform_after(result, config, interface):
        fired.append("after")
        return ToolResult(content="transformed", private=result.private)

    toolset = FunctionToolset([EchoTool.as_tool()])

    # Gated OFF: neither plugin is enabled.
    off = await drive_tool_call(
        toolset,
        _echo_call(call_id="off"),
        config=DEFAULT_CONFIG.with_(plugins={}),
        capabilities=[build_tool_execution_capability()],
    )
    assert fired == []
    assert _tool_returns(off)[0].content == "echoed: hi"

    # Gated ON (plugin_name falls back to the function name for a test module).
    fired.clear()
    on = await drive_tool_call(
        toolset,
        _echo_call(call_id="on"),
        config=DEFAULT_CONFIG.with_(
            plugins={"record_before": {}, "transform_after": {}}
        ),
        capabilities=[build_tool_execution_capability()],
    )
    assert fired == ["before", "after"]
    assert _tool_returns(on)[0].content == "transformed"


async def test_before_hook_plugin_exception_becomes_model_retry():
    """A blocking `@before` hook raises `PluginException`; the capability turns
    it into a `ModelRetry` so the model sees a retry prompt (its cue to react),
    not a crash - and the tool body never runs."""

    @before((EchoTool,))
    async def block(args, config, interface):
        raise PluginException("blocked by guard")

    result = await drive_tool_call(
        FunctionToolset([EchoTool.as_tool()]),
        _echo_call(),
        config=DEFAULT_CONFIG.with_(plugins={"block": {}}),
        capabilities=[build_tool_execution_capability()],
    )

    retries = _retries(result)
    assert len(retries) == 1
    assert "blocked by guard" in str(retries[0].content)
    # body never produced a result
    assert _tool_returns(result) == []
