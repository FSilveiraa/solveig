"""Shared tool-call replay: reconstruct one recorded call's display from its
persisted `ToolReturnPart`, reusing the tool's own `replay()` (which is
`display_header()` + `ToolResult.display_content()` - the same header a live
`execute()` shows). Used by the reactive transcript (on session resume) so
replay flows through the one render path, not a special-cased imperative one.

Kept dependency-light (no `solveig.interface` import at module load) so the
Textual transcript can import it without a cycle.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from pydantic import ValidationError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ToolCallPart,
    ToolReturnPart,
)

from solveig.tools.available import tool_classes
from solveig.tools.result import ToolResult

if TYPE_CHECKING:
    from solveig.interface.base import SolveigInterface


def build_returns_map(
    messages: Sequence[ModelMessage],
) -> dict[str, ToolReturnPart]:
    """tool_call_id -> its persisted ToolReturnPart, for O(1) pairing."""
    returns: dict[str, ToolReturnPart] = {}
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    returns[part.tool_call_id] = part
    return returns


async def replay_tool_call(
    interface: SolveigInterface,
    call: ToolCallPart,
    return_part: ToolReturnPart,
) -> None:
    """Render one recorded call inside its own collapsible group: the tool's
    `replay()` (header + result body), or a generic render if the tool isn't a
    `BaseTool` (a not-yet-converted plugin function) or its stored args no
    longer validate against the tool's current schema (a renamed/removed field
    since the session was recorded)."""
    result = ToolResult(content=return_part.content, private=return_part.metadata or {})
    tool_cls = tool_classes().get(call.tool_name)

    if tool_cls is not None:
        try:
            instance = tool_cls.model_validate(call.args_as_dict())
        except ValidationError:
            tool_cls = None

    if tool_cls is None:
        async with interface.with_group(call.tool_name) as group:
            await result.display_content(group)
        return

    async with interface.with_group(instance.title) as group:
        await instance.replay(group, result)
