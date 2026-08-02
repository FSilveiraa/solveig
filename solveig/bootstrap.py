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
from solveig.interface.base import SolveigInterface
from solveig.plugins.discovery import ON_SCANNED, discover_plugins, report_plugins
from solveig.plugins.hooks import hooks_config_map
from solveig.plugins.tools import PLUGIN_TOOLS, config_model_of, plugin_tool_name
from solveig.tools.core import CORE_TOOLS


def compose_core_tools() -> None:
    """Feed config the core tool list — one config field per tool."""
    SolveigConfig.compose_tools(
        [(tool.tool_name(), tool.config_model) for tool in CORE_TOOLS]
    )


def compose_plugin_sections() -> None:
    """Rebuild `plugins.tools` and `plugins.hooks` from whatever is registered.

    Subscribed to `ON_SCANNED` below, so it is a REACTION to the plugin set
    changing rather than a step a caller has to remember after
    `discover_plugins`. That pairing was the bug: the registry and the schema
    are two globals, nothing kept them in sync, and a stale schema does not
    fail - `extra="allow"` hands back a raw dict for the plugin's section and
    the mismatch only surfaces as an AttributeError deep inside a hook.

    Config cannot subscribe to this itself: it is imported by nearly everything
    and must not import the plugin packages back. So the wiring lives here, one
    layer above both, and neither module learns about the other."""
    SolveigConfig.compose_plugin_tools(
        [(plugin_tool_name(e), config_model_of(e)) for e in PLUGIN_TOOLS]
    )
    SolveigConfig.compose_plugin_hooks(list(hooks_config_map().items()))


ON_SCANNED.append(compose_plugin_sections)


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
    # Recomposition rides on the scan (ON_SCANNED), so this does not pair the
    # two by hand any more - and neither does anything else that scans.
    discover_plugins(config.plugins.paths)

    # Only the LIVE config needs bringing up to the new classes: recomposition
    # swaps the class behind plugins.tools/hooks, and this instance still holds
    # objects of the old one. It keeps its identity, and its subscriptions.
    config.rebuild_plugin_sections()

    # NOTE: nothing re-registers subcommands here. `discover_plugins` empties the
    # plugin store before the rescan, and every `@tool`/`@subcommand` in a
    # scanned module refills it on import - so a plugin deleted from disk loses
    # its command by simply never declaring it again.
    await report_plugins(config, interface)


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

    return SolveigConfig.build(cli_args=cli_args)
