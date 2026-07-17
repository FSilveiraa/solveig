"""Tier-2 plumbing tests for the tool bridge + tool-execution capability.

These drive the *framework* surface the migration introduced, not tool bodies:
`BaseTool.as_tool()` flattening/schema, and `build_tool_execution_capability`
running the plugin `@before`/`@after` hooks and rendering a `ToolResult` into
the `ToolReturn` the model sees. They couple to pydantic-ai's schema/message
layer on purpose - they're the early-warning system for a framework change
that breaks the bridge.
"""

import asyncio
import warnings

import pytest
from pydantic import Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets.abstract import AbstractToolset
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai.usage import RunUsage

from solveig.agent import build_loop_capability, build_tool_execution_capability
from solveig.context import SolveigContext
from solveig.conversation import Conversation
from solveig.exceptions import PluginException
from solveig.plugins.hooks import after, before, clear_hooks
from solveig.sessions.manager import SessionManager
from solveig.tools.available import AVAILABLE_TOOLS, tool_classes
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


def _context(config, interface) -> SolveigContext:
    """A `SolveigContext` with a fresh `Conversation`/`SessionManager` -
    plumbing tests below don't assert on those, they just need real objects
    since capabilities now read them from `ctx.deps` instead of closures."""
    return SolveigContext(
        config=config,
        interface=interface,
        conversation=Conversation(),
        session_manager=SessionManager(config=config),
    )


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
    return await agent.run("go", deps=_context(config, interface))


def _run_context(config, interface) -> RunContext[SolveigContext]:
    """A real `RunContext` carrying live `SolveigContext` deps, for driving
    `toolset.get_tools(ctx)` directly (pydantic-ai's own toolset introspection
    API) without going through a full `Agent.run()`."""
    return RunContext(
        deps=_context(config, interface),
        model=TestModel(),
        usage=RunUsage(),
        max_retries=1,
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

    async def execute(self, config, interface) -> ToolResult:  # type: ignore[no-untyped-def]
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

    await agent.run(
        "hi",
        deps=SolveigContext(  # type: ignore[arg-type]
            config=None, interface=None, conversation=None, session_manager=None
        ),
    )

    tool_defs = model.last_model_request_parameters.function_tools
    edit_def = next(t for t in tool_defs if t.name == "edit")
    params = edit_def.parameters_json_schema.get("properties", {})
    assert {"path", "old_string", "new_string", "replace_all"} <= set(params)
    assert "params" not in params  # not nested under a single model param


# ---------------------------------------------------------------------------
# build_tool_execution_capability: result rendering + hooks + retries
# ---------------------------------------------------------------------------


async def test_mcp_style_tool_is_grouped_approved_and_displayed():
    """A plain-function tool (the shape an MCP tool call actually has - no
    `BaseTool` instance) must get the same group/approve/display treatment as
    a typed tool, not run invisibly and unapproved. Regression test for a gap
    where MCP tool calls executed with zero group, zero display, and zero
    `ask_choice` at all."""

    async def search(objective: str) -> dict:
        return {"results": ["a", "b"]}

    interface = MockInterface(choices=[0])  # approve
    result = await drive_tool_call(
        FunctionToolset([search]),
        ToolCallPart(
            tool_name="search", args={"objective": "find stuff"}, tool_call_id="c1"
        ),
        interface=interface,
        capabilities=[build_tool_execution_capability()],
    )

    assert any(g.startswith("START: MCP: search") for g in interface.groups)
    assert any(g.startswith("END: MCP: search") for g in interface.groups)
    assert any("Allow this MCP tool call?" in q for q in interface.questions)
    returns = _tool_returns(result)
    assert len(returns) == 1
    assert returns[0].content == {"results": ["a", "b"]}


async def test_mcp_style_tool_decline_skips_the_call_entirely():
    """Declining ("Don't run") must not invoke the underlying tool at all,
    and the model must see a clear decline message, not a real result."""
    called = False

    async def search(objective: str) -> dict:
        nonlocal called
        called = True
        return {"results": ["a", "b"]}

    interface = MockInterface(choices=[2])  # "Don't run"
    result = await drive_tool_call(
        FunctionToolset([search]),
        ToolCallPart(
            tool_name="search", args={"objective": "find stuff"}, tool_call_id="c1"
        ),
        interface=interface,
        capabilities=[build_tool_execution_capability()],
    )

    assert called is False
    returns = _tool_returns(result)
    assert len(returns) == 1
    assert "declined" in returns[0].content


async def test_mcp_style_tool_inspect_first_then_send():
    """ "Run and inspect result first" actually runs the tool and shows the
    result before asking again - if the user then says yes, the real result
    reaches the model."""

    async def search(objective: str) -> dict:
        return {"results": ["a", "b"]}

    interface = MockInterface(choices=[1, 0])  # inspect first, then send
    result = await drive_tool_call(
        FunctionToolset([search]),
        ToolCallPart(
            tool_name="search", args={"objective": "find stuff"}, tool_call_id="c1"
        ),
        interface=interface,
        capabilities=[build_tool_execution_capability()],
    )

    assert any("Send this result to the assistant?" in q for q in interface.questions)
    returns = _tool_returns(result)
    assert returns[0].content == {"results": ["a", "b"]}


async def test_mcp_style_tool_inspect_first_then_withhold():
    """ "Run and inspect result first" still runs the tool (so the user can
    see the output) but must not send it to the model if the user then says
    no - the model must see a decline message instead of the real result."""
    called = False

    async def search(objective: str) -> dict:
        nonlocal called
        called = True
        return {"results": ["a", "b"]}

    interface = MockInterface(choices=[1, 1])  # inspect first, then withhold
    result = await drive_tool_call(
        FunctionToolset([search]),
        ToolCallPart(
            tool_name="search", args={"objective": "find stuff"}, tool_call_id="c1"
        ),
        interface=interface,
        capabilities=[build_tool_execution_capability()],
    )

    assert called is True  # it did run, just wasn't sent
    returns = _tool_returns(result)
    assert "declined to send it" in returns[0].content


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


# ---------------------------------------------------------------------------
# FilteredToolset: live no_commands / plugin gating without a rebuild
# ---------------------------------------------------------------------------


async def test_filtered_toolset_hides_command_live_without_rebuild():
    """`no_commands` gating is evaluated live, per step, against
    `ctx.deps.config` - the same built toolset must expose `command` with
    commands on and hide it with them off, with NO `rebuild()` in between."""
    AVAILABLE_TOOLS.rebuild(DEFAULT_CONFIG)  # membership built once
    toolset = AVAILABLE_TOOLS.toolset

    on = _run_context(DEFAULT_CONFIG.with_(no_commands=False), MockInterface())
    off = _run_context(DEFAULT_CONFIG.with_(no_commands=True), MockInterface())

    tools_on = await toolset.get_tools(on)
    tools_off = await toolset.get_tools(off)  # same toolset object, no rebuild

    assert "command" in tools_on
    assert "command" not in tools_off


# ---------------------------------------------------------------------------
# build_loop_capability: autonomy gate + comment interleaving
# ---------------------------------------------------------------------------


def _user_prompts(result) -> list[str]:
    return [
        str(part.content)
        for message in result.all_messages()
        for part in getattr(message, "parts", [])
        if isinstance(part, UserPromptPart)
    ]


def _two_round_agent(config, interface):
    """An agent whose model calls `echo` once, then replies with text - so there
    is exactly one CallToolsNode->next boundary for the loop capability to act
    on. Both real capabilities are wired."""
    model = create_mock_model(
        ModelResponse(parts=[_echo_call()]),
        ModelResponse(parts=[TextPart(content="done")]),
    )
    agent = Agent(
        model,
        deps_type=SolveigContext,
        toolsets=[FunctionToolset([EchoTool.as_tool()])],
        capabilities=[
            build_loop_capability(),
            build_tool_execution_capability(),
        ],
    )
    return agent, model


async def test_autonomy_gate_blocks_until_queue_fed_then_injects_comment():
    """With `disable_autonomy`, the run blocks at the tool-round boundary until
    `pending_queue` is fed; the fed comment is then injected into the run as a
    `UserPromptPart` and the run resumes."""
    config = DEFAULT_CONFIG.with_(disable_autonomy=True)
    interface = MockInterface()
    agent, model = _two_round_agent(config, interface)

    task = asyncio.create_task(agent.run("go", deps=_context(config, interface)))
    # let it get through round 1 (the tool call) and reach the gate
    for _ in range(500):
        await asyncio.sleep(0)
        if model.get_call_count() >= 1:
            break
    await asyncio.sleep(0.02)

    # Blocked: round 2 can't happen until the queue is fed (empty queue -> the
    # gate's `await queue.get()` suspends the whole run).
    assert not task.done()
    assert model.get_call_count() == 1

    interface.pending_queue.put_nowait("go ahead")
    result = await asyncio.wait_for(task, timeout=2)

    assert model.get_call_count() == 2  # resumed
    assert any("go ahead" in p for p in _user_prompts(result))


async def test_comment_interleaving_drains_queue_without_blocking():
    """With autonomy on, the gate never blocks, but anything already queued is
    still drained into the run (injected as a `UserPromptPart`) at the next
    tool-round boundary."""
    config = DEFAULT_CONFIG  # disable_autonomy=False
    interface = MockInterface()
    interface.pending_queue.put_nowait("mid-run note")
    agent, _ = _two_round_agent(config, interface)

    result = await agent.run("go", deps=_context(config, interface))

    assert any("mid-run note" in p for p in _user_prompts(result))
