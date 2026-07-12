"""Builds the pydantic-ai Agent that drives a single conversation turn.

Cheap enough to rebuild per turn: the `Provider` (the real network client) is
held separately in a `ProviderRef` and reused across turns; only the `Agent`
wrapper (model + toolset + capability) is rebuilt, so runtime config changes
(model, briefing, disable_autonomy) take effect on the very next request
without restarting anything.
"""

from pydantic_ai import Agent, ModelResponse, RunContext, TextPart, ThinkingPart
from pydantic_ai.capabilities import Hooks
from pydantic_ai.models import Model
from pydantic_graph import End

from solveig.config import SolveigConfig
from solveig.context import SolveigContext
from solveig.interface import SolveigInterface
from solveig.llm.api import ProviderRef, get_model
from solveig.tools.available import AVAILABLE_TOOLS


def build_agent(
    config: SolveigConfig,
    provider_ref: ProviderRef,
    interface: SolveigInterface,
    system_prompt: str,
    model: Model | None = None,
) -> Agent[SolveigContext, str]:
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
        deps_type=SolveigContext,
        instructions=system_prompt,
        toolsets=[AVAILABLE_TOOLS.toolset],
        capabilities=[build_loop_capability(config, interface)],
    )


def build_loop_capability(
    config: SolveigConfig, interface: SolveigInterface
) -> Hooks[SolveigContext]:
    """Build the per-agent capability driving live display, interleaving, and autonomy."""
    hooks: Hooks[SolveigContext] = Hooks()

    @hooks.on.before_node_run
    async def display_new_response(ctx: RunContext[SolveigContext], node):
        if Agent.is_call_tools_node(node):
            await _display_response(interface, node.model_response)
        return node

    @hooks.on.after_node_run
    async def gate_and_interleave(ctx: RunContext[SolveigContext], node, result):
        # Both concerns only apply at the CallToolsNode -> next-node boundary
        # - the point where tool execution for this round has just finished.
        # Draining after every node (e.g. right after UserPromptNode, before
        # any tool has even run) would steal a pre-typed comment before the
        # autonomy gate below ever gets a chance to consume it.
        if not Agent.is_call_tools_node(node):
            return result

        queue = interface.pending_queue

        # Autonomy gate first, so it consumes exactly the go-ahead it's
        # waiting for - draining the queue before this point would let the
        # always-on drain below steal it and leave the gate blocked forever.
        if config.disable_autonomy and not isinstance(result, End):
            await interface.update_stats(status="Awaiting confirmation to continue")
            comment = await queue.get()
            await interface.notify_pending_queue_changed()
            await interface.update_stats(status=None)
            ctx.enqueue(comment, priority="asap")

        # Always-on drain: anything else typed - while this round of tools
        # was executing, or freshly arrived while the gate above was blocked
        # - gets delivered at the next opportunity too, regardless of
        # autonomy mode.
        while not queue.empty():
            ctx.enqueue(queue.get_nowait(), priority="asap")
            await interface.notify_pending_queue_changed()

        return result

    return hooks


async def _display_response(
    interface: SolveigInterface, model_response: ModelResponse
) -> None:
    for part in model_response.parts:
        if isinstance(part, ThinkingPart) and part.content:
            await interface.display_text_box(
                part.content, title="Reasoning", collapsed=True, italic=True
            )
        elif isinstance(part, TextPart) and part.content:
            await interface.display_section("Assistant")
            await interface.display_comment(part.content)
