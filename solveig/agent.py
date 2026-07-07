"""Builds the pydantic-ai Agent that drives a single conversation turn.

Cheap enough to rebuild per turn: the `Provider` (the real network client) is
held separately in a `ProviderRef` and reused across turns; only the `Agent`
wrapper (model + toolset + capability) is rebuilt, so runtime config changes
(model, briefing, disable_autonomy) take effect on the very next request
without restarting anything.
"""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.llm.api import ProviderRef, get_model
from solveig.schema.deps import SolveigDeps
from solveig.schema.loop_capability import build_loop_capability
from solveig.schema.toolset import AVAILABLE_TOOLS


def build_agent(
    config: SolveigConfig,
    provider_ref: ProviderRef,
    interface: SolveigInterface,
    system_prompt: str,
    model: Model | None = None,
) -> Agent[SolveigDeps, str]:
    """Build the per-turn Agent.

    `model` lets callers (tests, the mock demo) inject a pydantic-ai `Model`
    directly (e.g. `FunctionModel`/`TestModel`), bypassing `provider_ref`'s
    Provider/API-key resolution entirely.
    """
    if model is not None:
        resolved_model = model
    else:
        assert config.model is not None, "build_agent requires config.model to be set"
        resolved_model = get_model(config.api_type, provider_ref.provider, config.model)
    return Agent(
        resolved_model,
        deps_type=SolveigDeps,
        instructions=system_prompt,
        toolsets=[AVAILABLE_TOOLS.toolset],
        capabilities=[build_loop_capability(config, interface)],
    )
