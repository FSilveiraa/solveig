"""Startup sequencing — compose the runtime config schema, then parse.

This is composition-root work, which is why it lives above config rather than
inside it: it needs `tools` and `plugins` to know what the schema should
contain, and both sit above config. Config itself only knows *how* to build a
section (`SolveigConfig.compose_*`), never what goes in one.

The two-phase parse exists because plugin discovery is itself configurable:
`plugins.paths` has to be read before the plugins can be imported, and the
plugins have to be imported before their config models exist to validate
against.

    1. compose core tools (known at import) and parse once
    2. discover plugins using that config
    3. compose the plugin tool/hook sections from what was discovered
    4. parse again, now validating plugin config against the real models
"""

from __future__ import annotations

from solveig.config import SolveigConfig
from solveig.plugins import discover_plugins
from solveig.plugins.hooks import hooks_config_map
from solveig.plugins.tools import PLUGIN_TOOLS, config_model_of, plugin_tool_name
from solveig.tools import CORE_TOOLS


def compose_core_tools() -> None:
    """Feed config the core tool list — one config field per tool."""
    SolveigConfig.compose_tools(
        [(tool.tool_name(), tool.config_model) for tool in CORE_TOOLS]
    )


def compose_plugin_tools() -> None:
    """Feed config the discovered plugin tools. Call after `discover_plugins`."""
    SolveigConfig.compose_plugin_tools(
        [(plugin_tool_name(e), config_model_of(e)) for e in PLUGIN_TOOLS]
    )


def compose_plugin_hooks() -> None:
    """Feed config the discovered hooks. Call after `discover_plugins`."""
    SolveigConfig.compose_plugin_hooks(list(hooks_config_map().items()))


async def parse_config_and_prompt(
    cli_args: list[str] | None = None,
) -> SolveigConfig:
    """The full two-phase startup parse. See the module docstring."""
    compose_core_tools()
    # Provisional parse: discovery only needs `plugins.paths`, and the plugin
    # schema doesn't exist yet, so this config is thrown away.
    discover_plugins(SolveigConfig.parse(cli_args=cli_args))

    compose_plugin_tools()
    compose_plugin_hooks()
    return SolveigConfig.build(cli_args=cli_args)
