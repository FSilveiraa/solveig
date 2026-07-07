"""The tool calling contract - what a tool author's function looks like going
in, and what it hands back going out. `@tool` and `ToolResult`/`Finalizer`
are two halves of the same thing and are kept together on purpose: a tool
author only ever needs this one file to know the full shape of a tool.

**Input side (`@tool`)**: a tool author writes
`async def read(config, interface, *args) -> ToolResult`. `@tool` rewrites
the function pydantic-ai actually sees to `(ctx: RunContext[SolveigDeps],
*args)`, resolving `config`/`interface` from `ctx.deps` fresh on every call -
so a different live `SolveigDeps` at call time than at registration time
still flows through correctly (needed for a future hot-swappable-interface
session).

Built on `makefun` rather than a hand-rolled signature rewrite: pydantic-ai's
`function_schema()` calls both `inspect.signature()` (parameter list/order)
and `get_type_hints()` (annotation resolution, reads raw `__annotations__`/
`__globals__` - does not respect ad-hoc `__signature__` overrides).
`makefun.create_function` builds a real function that satisfies both.

**Output side (`ToolResult`/`Finalizer`)**: tool functions and `@before`/
`@after` hooks (`solveig/schema/toolset.py`) all deal in `ToolResult`, never
in `pydantic_ai.messages.ToolReturn` directly. A `Finalizer` (always the
outermost toolset wrapper) is the only place a `ToolResult` gets converted
into a `ToolReturn`.
"""

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import makefun
from pydantic_ai import RunContext
from pydantic_ai.messages import ToolReturn
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.toolsets.wrapper import WrapperToolset

from solveig.schema.deps import SolveigDeps

# ---------------------------------------------------------------------------
# Input side - @tool
# ---------------------------------------------------------------------------


def _ctx_signature(fn: Callable[..., Any]) -> inspect.Signature:
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    if len(params) < 2 or params[0].name != "config" or params[1].name != "interface":
        raise TypeError(
            f"@tool functions must take (config, interface, ...) - got {fn.__name__}{sig}"
        )
    ctx_param = inspect.Parameter(
        "ctx",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        annotation=RunContext[SolveigDeps],
    )
    return sig.replace(parameters=[ctx_param, *params[2:]])


def tool[F: Callable[..., Awaitable[Any]]](fn: F) -> F:
    """Register `fn` as a pydantic-ai tool function with `ctx` hidden from its authored signature."""
    new_sig = _ctx_signature(fn)

    async def impl(*args: Any, **kwargs: Any) -> Any:
        bound = new_sig.bind(*args, **kwargs)
        bound.apply_defaults()
        arguments = dict(bound.arguments)
        ctx: RunContext[SolveigDeps] = arguments.pop("ctx")
        return await fn(ctx.deps.config, ctx.deps.interface, **arguments)

    wrapper = makefun.create_function(
        new_sig,
        impl,
        func_name=fn.__name__,
        doc=fn.__doc__ or "",
        module_name=fn.__module__,
    )
    wrapper.tool_name = fn.__name__  # type: ignore[attr-defined]
    return wrapper  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Output side - ToolResult / Finalizer
# ---------------------------------------------------------------------------


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
        ctx: RunContext[SolveigDeps],
        tool: ToolsetTool[SolveigDeps],
    ) -> Any:
        result = await super().call_tool(name, tool_args, ctx, tool)
        if not isinstance(result, ToolResult):
            return result
        return ToolReturn(
            return_value=to_assistant_text(result), metadata=result.private
        )
