"""`@tool` - hides pydantic-ai's RunContext/SolveigDeps plumbing from tool authors.

A tool author writes `async def read(config, interface, *args) -> ToolResult`.
`@tool` rewrites the function pydantic-ai actually sees to
`(ctx: RunContext[SolveigDeps], *args)`, resolving `config`/`interface` from
`ctx.deps` fresh on every call - so a different live `SolveigDeps` at call
time than at registration time still flows through correctly (needed for a
future hot-swappable-interface session).

Built on `makefun` rather than a hand-rolled signature rewrite: pydantic-ai's
`function_schema()` calls both `inspect.signature()` (parameter list/order)
and `get_type_hints()` (annotation resolution, reads raw `__annotations__`/
`__globals__` - does not respect ad-hoc `__signature__` overrides).
`makefun.create_function` builds a real function that satisfies both.
"""

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

import makefun
from pydantic_ai import RunContext

from solveig.schema.deps import SolveigDeps


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
