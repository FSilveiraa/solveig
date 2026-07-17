"""The one orchestration path shared by an LLM-driven tool call and a
user-typed `/tool` subcommand.

Both need the *same* wrapping around a tool's body: open the call's collapsible
group, show the tool's intent (`display_header`), run the plugin `@before`
hooks (shellcheck etc.), run the body, run the `@after` hooks (trafilatura
etc.), and hand back the (possibly transformed) `ToolResult`. This is also
the one place that scopes `interface` to the call's own group before handing
it to `instance.execute()` - so a tool body never sees the root interface
directly, only its own group.

Only how a blocking `PluginException` is surfaced differs between the
callers: the agent turns it into a `ModelRetry` (the model reacts); the
subcommand displays an error (there's no model to answer). `run_tool_and_hooks`
lets it propagate; each caller translates.

This is the single home for the group + hook flow the pre-migration
`BaseTool.solve()` owned - it must not be duplicated between `agent.py` and
`subcommand/runner.py`.
"""

from typing import Any

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.plugins.hooks import AFTER_HOOKS, BEFORE_HOOKS, plugin_name
from solveig.tools.base import BaseTool
from solveig.tools.core.task import TasksTool
from solveig.tools.result import ToolResult


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
    async with interface.with_group(
        instance.title,
        auto_collapse=config.auto_collapse_tools
        and not isinstance(instance, TasksTool),
    ) as group:
        # Intent first (file header, command text, URL) so a @before hook's
        # prompt appears with the operation already visible above it.
        await instance.display_header(group)

        for before_hook in BEFORE_HOOKS.get(tool_name, ()):
            if plugin_name(before_hook) in config.plugins:
                await before_hook(instance.model_dump(), config, group)

        result = await instance.execute(config, group)
        if not isinstance(result, ToolResult):
            return result

        for after_hook in AFTER_HOOKS.get(tool_name, ()):
            if plugin_name(after_hook) in config.plugins:
                result = await after_hook(result, config, group)
        return result
