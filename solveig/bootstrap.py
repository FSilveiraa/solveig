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

from collections.abc import Iterable

from pydantic import ValidationError
from pydantic_settings.exceptions import SettingsError

from solveig.config import SolveigConfig
from solveig.exceptions import PluginException, ToolDisabledError
from solveig.interface.base import SolveigInterface
from solveig.plugins import discover_plugins
from solveig.plugins.hooks import hooks_config_map
from solveig.plugins.tools import PLUGIN_TOOLS, config_model_of, plugin_tool_name
from solveig.subcommands.base import _PENDING, Subcommand
from solveig.tools import CORE_TOOLS
from solveig.tools.base import BaseTool
from solveig.tools.orchestration import run_tool_and_hooks


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


def _tool_handler(tool_cls: type[BaseTool]):
    """A tool's `/command` as a plain subcommand handler: it declares the two
    dependencies it needs by annotating them, takes the raw words, and runs the
    tool through the ONE execution seam - so a hand-typed `/read` gets the same
    consent, hooks and group posture a model-issued call does.

    Built here rather than in `tools/`: this closure has to name both the tool
    and the orchestrator that runs it, and `tools/base.py` cannot reach the
    orchestrator without a cycle. Keeping it here is also what lets `tools/`
    import nothing from `subcommands/`.
    """

    async def handler(
        config: SolveigConfig, interface: SolveigInterface, *tokens: str
    ) -> None:
        try:
            instance = tool_cls.from_cli_tokens(list(tokens))
        except (SettingsError, ValidationError) as e:
            await interface.display_error(str(e))
            await interface.display_info(
                f"Usage: {tool_cls.subcommands[0]} {tool_cls.subcommand_usage()}"
            )
            return
        try:
            await run_tool_and_hooks(instance, config, interface)
        except (PluginException, ToolDisabledError) as e:
            await interface.display_error(str(e))

    return handler


def register_tool_subcommands(tools: Iterable[type[BaseTool] | object]) -> None:
    """Push one `Subcommand` per tool that opted in by declaring trigger names.

    Runs at startup instead of at class creation because the tool set is not
    known until plugin discovery. A plugin tool registered as a plain callable
    has no CLI schema to parse against, so only `BaseTool` subclasses are
    considered.
    """
    for entry in tools:
        if not (isinstance(entry, type) and issubclass(entry, BaseTool)):
            continue
        if not entry.subcommands:
            continue
        _PENDING.append(
            Subcommand.from_handler(
                _tool_handler(entry),
                subcommands=list(entry.subcommands),
                section="tools",
                description=entry.subcommand_description(),
                usage=entry.subcommand_usage(),
                tool_name=entry.tool_name(),
            )
        )


async def parse_config_and_prompt(
    cli_args: list[str] | None = None,
) -> SolveigConfig:
    """The full two-phase startup parse. See the module docstring."""
    compose_core_tools()
    # Discovery needs exactly one setting, and the plugin schema does not exist
    # yet — so read that setting through the normal source stack and let the
    # object die on this line. Nothing is handed a half-composed config, which
    # is what makes the config built below the only one that ever exists.
    discover_plugins(SolveigConfig.parse(cli_args=cli_args).plugins.paths)

    compose_plugin_tools()
    compose_plugin_hooks()

    # Tool commands, now that the tool set is settled: core first, then whatever
    # discovery turned up. The registry reads the pending list when it is built.
    register_tool_subcommands(CORE_TOOLS)
    register_tool_subcommands(PLUGIN_TOOLS)

    return SolveigConfig.build(cli_args=cli_args)
