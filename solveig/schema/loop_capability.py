"""The conversation-loop capability: autonomy gate + live per-turn display.

Built as a pydantic-ai `Hooks` capability rather than manual `agent.iter()`/
`AgentRun.next()` stepping, so `run.py` can drive everything through a plain
`agent.run()` call - `before_node_run`/`after_node_run` fire uniformly
whichever way the graph is driven (confirmed against installed pydantic-ai
2.5.0 source, `capabilities/abstract.py`), so there's no need to give up the
simpler entry point just to observe/pause between node transitions.

Two independent concerns live here, both hooked off the same node
transition (`CallToolsNode` -> next node):

- **Comment interleaving** (always on): drains `interface.pending_queue`
  (whatever the user has typed and not yet had delivered) and forwards each
  item into the run via `ctx.enqueue(..., priority='asap')` - pydantic-ai's
  own mechanism delivers it into the next `ModelRequest`, or redirects an
  about-to-end run into one more turn. Nothing here decides *whether* to
  send it, only *that* it gets forwarded as soon as possible.
- **Autonomy gate** (`config.disable_autonomy` only): after tool execution
  finishes and the run is about to continue to another model turn (not
  about to `End`), block until the user has typed something before letting
  it proceed - a plain go-ahead, not a comment requirement independent of
  autonomy (that's what the always-on drain above already handles).
"""

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import Hooks
from pydantic_ai.messages import ModelResponse, TextPart, ThinkingPart
from pydantic_graph import End

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.deps import SolveigDeps


def build_loop_capability(
    config: SolveigConfig, interface: SolveigInterface
) -> Hooks[SolveigDeps]:
    """Build the per-agent capability driving live display, interleaving, and autonomy."""
    hooks: Hooks[SolveigDeps] = Hooks()

    @hooks.on.before_node_run
    async def display_new_response(ctx: RunContext[SolveigDeps], node):
        if Agent.is_call_tools_node(node):
            await _display_response(interface, node.model_response)
        return node

    @hooks.on.after_node_run
    async def gate_and_interleave(ctx: RunContext[SolveigDeps], node, result):
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
