"""Dependency-injection container passed as RunContext.deps to every tool function."""

from dataclasses import dataclass
from typing import cast

from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface


@dataclass
class SolveigContext:
    config: SolveigConfig
    interface: SolveigInterface


def get_throwaway_context() -> RunContext[SolveigContext]:
    """A RunContext for toolset introspection outside a real agent run.

    `deps=None` - only safe against a toolset whose `get_tools()`/predicates
    don't dereference `ctx.deps` (e.g. a single MCPToolset's own
    `is_tool_allowed` filter, which closes over server config directly
    instead). NOT safe against `AVAILABLE_TOOLS.toolset`: its `is_tool_active`
    predicate reads `ctx.deps.config` and will raise `AttributeError` against
    a throwaway context - that combination needs a real `SolveigContext`.
    The cast is inherent to constructing a fake RunContext outside of a real
    agent run - `None` isn't a `SolveigContext` regardless of what the
    return type is annotated as.
    """
    return RunContext(
        deps=cast(SolveigContext, None),
        model=TestModel(),
        usage=RunUsage(),
        max_retries=1,
    )
