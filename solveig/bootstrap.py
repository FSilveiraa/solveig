"""Startup wiring that lives above both `tools` and `plugins`.

Composition-root work: it needs those packages to know what the schema should
contain, and both sit above config. Config itself only knows *how* to build a
section, never what goes in one.

The one ordering rule: a plugin's config model cannot exist until the plugin has
been imported. So the config is built from the sources first (`plugins.paths`
among them), and `discover_plugins` then imports whatever is on disk and types
the plugin sections.
"""

from __future__ import annotations

import warnings

from config import ConfigChange, ConfigSection, Created, Deleted, Updated
from solveig.config import SolveigConfig
from solveig.config.subcommands import prompt_for_field
from solveig.exceptions import UserCancel
from solveig.interface.base import SolveigInterface, Stat
from solveig.subcommands.base import PLUGIN_SUBCOMMANDS, SUBCOMMANDS
from solveig.tools.orchestration import tool_subcommand


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
        await config.set_and_wait(**{path: new_value})

    stat = interface.add_stat(label, read=lambda: config.get(path), on_click=edit)

    @config.on_change(path)
    async def _redraw(
        _section: ConfigSection, _changes: tuple[ConfigChange, ...]
    ) -> None:
        # Whoever changed it - this stat's own click, a /config set, an API
        # client correcting a bad model - the display follows the config rather
        # than the edit path, so there is one refresh rule instead of one per
        # writer.
        stat.refresh()

    return stat


# TODO: find an appropriate home for this, ideally something that
#  receives/declares PluginToolsConfig
def register_plugin_tool_subcommand_observer(config: SolveigConfig) -> None:
    """Subscribe the plugin-tools mirror to `config.plugins.tools`.

    Once per config, and BEFORE the first scan types `config.plugins.tools`. A
    notification with no observer is silently dropped — so an arrival that
    happens before this runs leaves that tool's `/command` unregistered for good.

    The mirror is a REACTION, so it hears about created, updated and deleted
    entries alike; nothing has to call this again when a plugin appears.
    """

    def _add_subcommand(tool_cls):
        if (sub := tool_subcommand(tool_cls)) is not None:
            for refused in SUBCOMMANDS.add(PLUGIN_SUBCOMMANDS, sub):
                warnings.warn(refused, stacklevel=2)

    def _delete_subcommand(tool_cls):
        for trigger in tool_cls.subcommands:
            PLUGIN_SUBCOMMANDS.pop(trigger, None)

    @config.plugins.tools.on_change()
    async def update_subcommands_for_plugin_tools(
        _config: ConfigSection, changes: tuple[ConfigChange, ...]
    ) -> None:
        for change in changes:
            match change:
                # An entry with no `tool_class` is an unowned block — config
                #  for a tool that was never discovered. It offers no
                #  `/command`; when its tool arrives, the `Updated` that
                #  re-types it registers one.
                case Created(value=entry) if entry.tool_class is not None:
                    _add_subcommand(entry.tool_class)
                case Updated(before=old, after=new):
                    if old.tool_class is not None:
                        _delete_subcommand(old.tool_class)
                    if new.tool_class is not None:
                        _add_subcommand(new.tool_class)
                case Deleted(value=entry) if entry.tool_class is not None:
                    _delete_subcommand(entry.tool_class)
