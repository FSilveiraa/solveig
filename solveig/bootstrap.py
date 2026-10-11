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

from config import ConfigSection, ConfigChange, Deleted, Created, Updated
from solveig.config import SolveigConfig
from solveig.config.subcommands import prompt_for_field
from solveig.exceptions import UserCancel
from solveig.interface.base import SolveigInterface, Stat
from solveig.plugins.discovery import discover_plugins, report_plugins
from solveig.plugins.hooks import hooks_config_map
from solveig.plugins.tools import PLUGIN_TOOLS
from solveig.subcommands.base import SUBCOMMANDS, PLUGIN_SUBCOMMANDS
from solveig.tools.orchestration import tool_subcommand


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
    discover_plugins(config.plugins.paths)

    # The plugin sections learn every config type that exists now: blocks for
    # discovered plugins become typed entries, and entries of plugins that are
    # gone go back to their data, kept but out of reach.
    # NOTE: this lives here, above config and plugins both, because config
    #  must not import the plugin packages.
    config.plugins.tools.resolve({
        tool.tool_name(): tool.config_model
        for tool in PLUGIN_TOOLS
    })
    config.plugins.hooks.resolve(hooks_config_map())

    # NOTE: nothing re-registers subcommands here. `discover_plugins` empties the
    # plugin store before the rescan, and every `@tool`/`@subcommand` in a
    # scanned module refills it on import - so a plugin deleted from disk loses
    # its command by simply never declaring it again.

    # HACK: bad composition, we call discovery.discover_plugins,
    # resolve the types ourselves, then call discovery.report_plugins.
    await report_plugins(config, interface)


async def parse_config_and_prompt(
    cli_args: list[str] | None = None,
) -> SolveigConfig:
    """The full two-phase startup parse. See the module docstring."""
    # Discovery needs exactly one setting, and the plugin schema does not exist
    # yet — so read that setting through the normal source stack and let the
    # object die on this line. Nothing is handed a half-composed config, which
    # is what makes the config built below the only one that ever exists.
    discover_plugins(SolveigConfig.parse(cli_args=cli_args).plugins.paths)

    return SolveigConfig.build(cli_args=cli_args)


def register_config_stat(
    interface: SolveigInterface,
    config: SolveigConfig,
    label: str,
    path: str,
) -> Stat:
    """Show `path` in the stats display, editable by clicking it.

    `path` is a full dotted path (`api.model`, not `model`) - the same one
    `config.set` takes, so a short name will not resolve.

    Reads through the path on every render rather than caching, so `config` stays
    the single home for the value; the observer below only says "redraw", never
    "here is the new value".
    """

    async def edit() -> None:
        # Type-aware: prompt_for_field picks the widget from the FIELD's type
        # (constrained -> choices, bool -> yes/no, list -> comma-separated).
        try:
            new_value = await prompt_for_field(path, config, interface)
        except UserCancel:
            return
        await config.set(**{path: new_value})

    stat = interface.add_stat(label, read=lambda: config.get(path), on_click=edit)

    @config.on_change(path)
    async def _redraw(_config: SolveigConfig, _paths: frozenset[str]) -> None:
        # Whoever changed it - this stat's own click, a /config set, an API
        # client correcting a bad model - the display follows the config rather
        # than the edit path, so there is one refresh rule instead of one per
        # writer.
        stat.refresh()

    return stat


# TODO: find an appropriate home for this, ideally something that
#  receives/declares PluginToolsConfig
def register_plugin_tool_subcommands(config: SolveigConfig) -> None:
    def _add_subcommand(tool_cls):
        if (sub := tool_subcommand(tool_cls)) is not None:
            for refused in SUBCOMMANDS.add(PLUGIN_SUBCOMMANDS, sub):
                warnings.warn(refused)

    def _delete_subcommand(tool_cls):
        for trigger in tool_cls.subcommands:
            PLUGIN_SUBCOMMANDS.pop(trigger, None)

    @config.plugins.tools.on_change
    async def update_subcommands_for_plugin_tools(_config: ConfigSection, changes: frozenset[ConfigChange]) -> None:
        for change in changes:
            match change:
                case Created(value=entry):
                    _add_subcommand(entry.tool_class)
                case Updated(before=old, after=new):
                    _delete_subcommand(old.tool_class)
                    _add_subcommand(new.tool_class)
                case Deleted(value=entry):
                    _delete_subcommand(entry.tool_class)
