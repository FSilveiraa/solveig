"""The tool result contract - what a tool function hands back, and how it
becomes the `ToolReturn` pydantic-ai actually sends to the model.

Tool functions take `ctx: SolveigContext` directly, like any pydantic-ai
tool - no decorator or signature adaptation involved. The
convention each tool follows (see `solveig/schema/tools/core/read.py` etc.) is to
destructure `config, interface = ctx.deps.config, ctx.deps.interface` as the
first line of the body, so the rest of the function reads exactly like
before pydantic-ai was introduced, while `ctx` itself stays available for
anything that needs it (`ctx.enqueue()`, `ctx.tool_call_id`, retries, ...).

Tool functions and `@before`/`@after` hooks (`solveig/schema/toolset.py`)
all deal in `ToolResult`, never in `pydantic_ai.messages.ToolReturn`
directly. A `Finalizer` (always the outermost toolset wrapper) is the only
place a `ToolResult` gets converted into a `ToolReturn`.
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.messages import ToolReturn
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.toolsets.wrapper import WrapperToolset

from solveig.schema.deps import SolveigContext, SolveigDeps


@dataclass
class ToolResult:
    """What a tool (or a hook rewriting its output) actually produced.

    `content` is the tool's real output - `None` for purely side-effecting
    calls with nothing to show (a plain write, delete, move, ...), and only
    ever set on a genuine success path. It's `Any`, not `str`: a tool can
    hand back a raw typed object (e.g. a `FileMetadata` instance for a
    metadata-only read) so hooks downstream can operate on the real object;
    stringification happens exactly once, in the finalizer.

    `metadata` is unconditionally serialized into the assistant-visible text
    if non-empty - no opt-out mechanism. If a tool or a hook writes something
    here, it's because they've decided the assistant should see it.

    `issues` is a chronologically-ordered list of warnings/errors - plain
    strings pass through as-is, `Exception`/`Warning` instances render as
    `{classname}: {msg}`.

    `private` never reaches the assistant. It's for data a tool or hook
    needs to pass to *other* hooks (or preserve for session-replay/
    introspection) without it being assistant-visible noise - e.g. `http`'s
    raw response headers, which `trafilatura` needs but the assistant doesn't.
    """

    content: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    issues: list[Exception | str] = field(default_factory=list)
    private: dict[str, Any] = field(default_factory=dict)


def _issue_line(issue: Exception | str) -> str:
    if isinstance(issue, Exception):
        return f"{issue.__class__.__name__}: {issue}"
    return str(issue)


def to_assistant_text(result: ToolResult) -> Any:
    """Build what the assistant actually reads from a `ToolResult`.

    `content` passes through untouched - even as a raw non-str object - when
    there's no metadata or issues to splice in, preserving the raw-object
    passthrough tools like `read`'s metadata-only path rely on.
    """
    if not result.metadata and not result.issues:
        return result.content

    sections = []
    if result.content:
        sections.append(str(result.content))
    if result.metadata:
        lines = "\n".join(f"- {k}: {v}" for k, v in result.metadata.items())
        sections.append(f"Metadata:\n{lines}")
    if result.issues:
        lines = "\n".join(f"- {_issue_line(issue)}" for issue in result.issues)
        sections.append(f"Issues:\n{lines}")
    return "\n---\n".join(sections)


class Finalizer(WrapperToolset[SolveigDeps]):
    """Always the outermost toolset wrapper - the only place a `ToolResult`
    becomes a `ToolReturn`. Everything inside (the tool itself, every
    `@before`/`@after` hook) works with the raw `ToolResult`, never this."""

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: SolveigContext,
        tool: ToolsetTool[SolveigDeps],
    ) -> Any:
        result = await super().call_tool(name, tool_args, ctx, tool)
        if not isinstance(result, ToolResult):
            return result
        return ToolReturn(
            return_value=to_assistant_text(result), metadata=result.private
        )
