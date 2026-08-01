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

import warnings

from solveig.config import SolveigConfig
from solveig.interface.base import SolveigInterface
from solveig.plugins.discovery import discover_plugins, report_plugins
from solveig.plugins.hooks import hooks_config_map
from solveig.plugins.tools import PLUGIN_TOOLS, config_model_of, plugin_tool_name
from solveig.tools.core import CORE_TOOLS


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


async def reload_plugins(config: SolveigConfig, interface: SolveigInterface) -> None:
    """The ONE path a change to the plugin set travels — startup reporting, a
    `plugins.paths` change, and (later) `/plugins reload` all take it.

    Discovery alone was never the whole job: whoever called it also had to
    recompose the config sections, refresh the subcommands and render the
    report, and each call site had to remember a different subset. That is the
    fetch → check → act shape this project is written against, so the
    obligations live here instead — the same argument that makes
    `Conversation.load()` fire the events a live turn fires.

    A reload reloads EVERYTHING plugin-related: `rescan_and_load_plugins` evicts
    deleted modules and re-imports changed ones, so working out which file moved
    would buy nothing a full rescan doesn't already give.
    """
    # Plugin declarations land in their stores as the rescan imports them, so a
    # refused trigger surfaces as a UserWarning from inside the import — the only
    # channel available there. Caught here, where there is an interface to show
    # it on. Kept apart from `errors`: a refused trigger is not a failure to
    # load, and rendering it as one would misreport a working plugin.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        errors = discover_plugins(config.plugins.paths)
    collisions = [str(w.message) for w in caught]

    # The discovered set decides the schema, so recompose before anything reads
    # plugin config, then bring the live config's sections up to the new
    # classes — `config` itself keeps its identity and its subscriptions.
    compose_plugin_tools()
    compose_plugin_hooks()
    config.rebuild_plugin_sections()

    # NOTE: nothing re-registers subcommands here. `discover_plugins` empties the
    # plugin store before the rescan, and every `@tool`/`@subcommand` in a
    # scanned module refills it on import - so a plugin deleted from disk loses
    # its command by simply never declaring it again.
    await report_plugins(config, interface, errors)
    for collision in collisions:
        await interface.display_warning(collision)


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

    return SolveigConfig.build(cli_args=cli_args)
