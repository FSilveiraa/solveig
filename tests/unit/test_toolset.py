"""Tier-2 plumbing tests for the tool bridge (`BaseTool.as_tool()` + toolset).

These drive the *framework* surface the migration introduced, not tool bodies:
the single-model-parameter flattening and its schema cleanliness. They're the
early-warning system for a pydantic-ai change that breaks the bridge - they
couple to pydantic-ai's schema/introspection on purpose.
"""

import warnings

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets.function import FunctionToolset

from solveig.context import SolveigContext
from solveig.tools.available import tool_classes
from solveig.tools.core.edit import EditTool


@pytest.mark.anyio
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


@pytest.mark.anyio
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
