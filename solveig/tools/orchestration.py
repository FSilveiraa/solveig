"""The one home for wrapping a tool call in its collapsible group.

Three paths live here so the group/consent/display posture isn't split across
modules:

- `run_tool_and_hooks` - a typed `BaseTool` call (LLM-driven or a user-typed
  `/tool` subcommand). Opens the call's group, shows the tool's intent
  (`display_header`), runs the plugin `@before` hooks (shellcheck etc.), runs
  the body, runs the `@after` hooks (trafilatura etc.), and returns the
  (possibly transformed) `ToolResult`. This is also the one place that scopes
  `interface` to the call's own group before handing it to `instance.execute()`
  - a tool body never sees the root interface, only its own group.
- `run_untyped_tool` - a plain-function/MCP call with no `BaseTool` instance and
  so no typed schema/consent of its own; gets a generic group + 3-way consent +
  display treatment instead.
- `replay_tool_call` - a call recorded in a session, re-presented from its
  stored `ToolReturnPart`. Same shape as the two above (look the tool up by
  name, rebuild the instance from its args, open its group, let the tool draw
  itself) but with `replay()` in place of `execute()`, since the result already
  exists. It lived in `sessions/` for a while purely because resume is what
  calls it — but it is tool display, not session storage, and the group posture
  it needs is the one defined here.

All three open the group through `open_tool_group`, the single home for the
auto-collapse policy. Only how a blocking `PluginException` is surfaced differs
between the typed callers: the agent turns it into a `ModelRetry` (the model
reacts), the subcommand displays an error (no model to answer);
`run_tool_and_hooks` lets it propagate and each caller translates.
"""

import json
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ToolCallPart,
    ToolReturnPart,
)

from solveig.config import SolveigConfig
from solveig.exceptions import ToolDisabledError
from solveig.interface.base import SolveigInterface
from solveig.plugins.hooks import AFTER_HOOKS, BEFORE_HOOKS, hook_name
from solveig.tools.available import tool_classes
from solveig.tools.base import BaseTool
from solveig.tools.core.task import TasksTool
from solveig.tools.result import ToolResult


def open_tool_group(
    interface: SolveigInterface,
    title: str,
    config: SolveigConfig,
    *,
    auto_collapse: bool = True,
):
    """Open a tool call's collapsible group with the shared auto-collapse policy:
    the config toggle AND the caller's own opt-out (e.g. Tasks never auto-
    collapse). The single place the group + auto_collapse convention lives for
    both the typed and untyped execution paths below."""
    return interface.with_group(
        title, auto_collapse=config.interface.auto_collapse_tools and auto_collapse
    )


async def run_tool_and_hooks(
    instance: BaseTool,
    config: SolveigConfig,
    interface: SolveigInterface,
) -> Any:
    """Open *instance*'s group, run it with its `@before`/`@after` hooks, and
    return whatever `execute()` produced, after any `@after` hook has
    transformed it (a non-`ToolResult` body result - e.g. from an MCP tool -
    passes through the after-hooks untouched). A `@before` hook raising
    `PluginException` propagates out for the caller to translate; `UserCancel`
    (not a `PluginException`) propagates as a real cancellation.
    """
    tool_name = instance.tool_name()
    # The single enable/disable enforcement point: both the LLM path and the
    # /tool subcommand path reach a tool through here, so a disabled tool is
    # refused uniformly (each caller translates ToolDisabledError). The LLM path
    # also filters disabled tools out of the schema upstream, making this a
    # belt-and-suspenders guard there and the *only* guard for the subcommand.
    if not config.is_tool_enabled(tool_name):
        raise ToolDisabledError(
            f"Tool '{tool_name}' is disabled (tools.{tool_name}.enabled=false)."
        )
    async with open_tool_group(
        interface,
        instance.title,
        config,
        auto_collapse=not isinstance(instance, TasksTool),
    ) as group:
        # Intent first (file header, command text, URL) so a @before hook's
        # prompt appears with the operation already visible above it.
        await instance.display_header(group)

        # Hooks are enabled-by-default; a hook disabled via plugins.hooks.<name>.
        # enabled=false is skipped here (the one gate, parallel to is_tool_enabled).
        for before_hook in BEFORE_HOOKS.get(tool_name, ()):
            if config.is_hook_enabled(hook_name(before_hook)):
                await before_hook(instance.model_dump(), config, group)

        result = await instance.execute(config, group)
        if not isinstance(result, ToolResult):
            return result

        for after_hook in AFTER_HOOKS.get(tool_name, ()):
            if config.is_hook_enabled(hook_name(after_hook)):
                result = await after_hook(result, config, group)
        return result


async def run_untyped_tool(
    config: SolveigConfig,
    interface: SolveigInterface,
    call: ToolCallPart,
    args: dict[str, Any],
    handler: Any,
) -> Any:
    """Group + approve + display a plain-function/MCP tool call - same
    visibility/consent posture as a BaseTool, but with no typed schema to build a
    proper header or decline ToolResult from. Mirrors ReadTool's run+send /
    run+inspect-then-decide / don't-run negotiation (minus the metadata-only
    middle ground), letting the user see the result before it's sent.
    `call.tool_name` is already the sanitized, prefixed name (an MCP tool's
    name carries its server prefix from `PrefixedToolset`, so the origin is
    visible without labeling the group — and a plain-function plugin tool
    isn't MCP at all)."""
    async with open_tool_group(interface, call.tool_name, config) as group:
        await group.display_text_box(
            json.dumps(args, indent=2, default=str), title="Args", language="json"
        )

        choice = await group.ask_choice(
            "Allow this tool call?",
            [
                "Run and send result",
                "Run and inspect result first",
                "Don't run",
            ],
        )

        if choice == 2:
            await group.display_warning("Rejected")
            return "User declined to run this tool."

        result = await handler(args)

        await group.display_text_box(str(result), title="Result", collapsed=choice == 0)

        if choice == 0:
            await group.display_success("Accepted")
            return result

        # choice == 1: ran and displayed the result above, now decide whether
        # to actually send it on.
        if (
            await group.ask_choice("Send this result to the assistant?", ["Yes", "No"])
        ) == 0:
            await group.display_success("Accepted")
            return result

        await group.display_warning("Rejected")
        return "User inspected the result and declined to send it to the assistant."


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

    # Replayed tool groups start collapsed: a resumed session is historical, so
    # the result body is folded away by default (same as a live run finishing
    # under the default auto_collapse_tools) - the user expands what they want.
    if tool_cls is None:
        async with interface.with_group(call.tool_name, auto_collapse=True) as group:
            await result.display_content(group)
        return

    async with interface.with_group(instance.title, auto_collapse=True) as group:
        await instance.replay(group, result)
