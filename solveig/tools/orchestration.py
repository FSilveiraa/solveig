"""The one home for wrapping a tool's execution in its collapsible group.

Two execution paths live here so the group/consent/display posture isn't split
across modules:

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

Both open the group through `open_tool_group`, the single home for the
auto-collapse policy. Only how a blocking `PluginException` is surfaced differs
between the typed callers: the agent turns it into a `ModelRetry` (the model
reacts), the subcommand displays an error (no model to answer);
`run_tool_and_hooks` lets it propagate and each caller translates.
"""

import json
from typing import Any

from pydantic_ai.messages import ToolCallPart

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.plugins.hooks import AFTER_HOOKS, BEFORE_HOOKS
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
    async with open_tool_group(
        interface,
        instance.title,
        config,
        auto_collapse=not isinstance(instance, TasksTool),
    ) as group:
        # Intent first (file header, command text, URL) so a @before hook's
        # prompt appears with the operation already visible above it.
        await instance.display_header(group)

        # Hooks are enabled-by-default (per-hook enable/disable config is
        # Sub-project B); every registered hook for this tool fires.
        for before_hook in BEFORE_HOOKS.get(tool_name, ()):
            await before_hook(instance.model_dump(), config, group)

        result = await instance.execute(config, group)
        if not isinstance(result, ToolResult):
            return result

        for after_hook in AFTER_HOOKS.get(tool_name, ()):
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
    `call.tool_name` is already the sanitized, prefixed name."""
    async with open_tool_group(interface, f"MCP: {call.tool_name}", config) as group:
        await group.display_text_box(
            json.dumps(args, indent=2, default=str), title="Args", language="json"
        )

        choice = await group.ask_choice(
            "Allow this MCP tool call?",
            [
                "Run and send result",
                "Run and inspect result first",
                "Don't run",
            ],
        )

        if choice == 2:
            await group.display_warning("Rejected")
            return "User declined to run this tool."

        async with group.with_cancellable(handler(args), status="Executing") as task:
            result = await task

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
