"""Dependency-injection container passed as RunContext.deps to every tool
function and agent-level Hooks capability - the single place "stuff about
this run" lives, instead of each capability closing over its own subset."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from solveig.config import SolveigConfig
from solveig.conversation import Conversation
from solveig.interface import SolveigInterface

if TYPE_CHECKING:
    # sessions.manager -> tools.available -> context would otherwise cycle.
    from solveig.sessions.manager import SessionManager


@dataclass
class SolveigContext:
    config: SolveigConfig
    interface: SolveigInterface
    conversation: Conversation
    session_manager: SessionManager


def get_introspection_context(deps: SolveigContext) -> RunContext[SolveigContext]:
    """A RunContext wrapping real deps, for toolset introspection (e.g.
    `MCPToolset.get_tools()`) outside a real agent run. The model and usage
    are stand-ins, but deps are real, so `ctx.deps`-reading predicates (like
    the FilteredToolset's `is_tool_active`) behave as they would mid-run."""
    return RunContext(
        deps=deps,
        model=TestModel(),
        usage=RunUsage(),
        max_retries=1,
    )
