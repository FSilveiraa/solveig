"""Startup wiring that lives above both `tools` and `plugins`.

Composition-root work: it needs those packages to know what the schema should
contain, and both sit above config. Config itself only knows *how* to build a
section, never what goes in one.

The one ordering rule: a plugin's config model cannot exist until the plugin has
been imported. So the config is built from the sources first (`plugins.paths`
among them), and `reload_plugins` then imports whatever is on disk and hands
those models to the plugin sections.
"""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Awaitable

from config import ConfigChange, ConfigSection, Created, Deleted, Updated
from solveig.config import SolveigConfig
from solveig.config.subcommands import prompt_for_field
from solveig.exceptions import UserCancel
from solveig.interface.base import SolveigInterface, Stat
from solveig.plugins.discovery import discover_plugins, report_plugins
from solveig.plugins.hooks import hooks_config_map
from solveig.subcommands.base import PLUGIN_SUBCOMMANDS, SUBCOMMANDS
from solveig.tools.orchestration import tool_subcommand


async def reload_plugins(config: SolveigConfig, interface: SolveigInterface) -> None:
    """The ONE path a change to the plugin set travels — startup, a
    `plugins.paths` change, and (later) `/plugins reload` all take it.

    Discovery alone was never the whole job: whoever called it also had to
    recompose the config sections and render the report, and each call site had
    to remember a different subset. That is the fetch → check → act shape this
    project is written against, so the obligations live here instead — the same
    argument that makes `Conversation.load()` fire the events a live turn fires.

    A reload reloads EVERYTHING plugin-related: `rescan_and_load_plugins` evicts
    deleted modules and re-imports changed ones, so working out which file moved
    would buy nothing a full rescan doesn't already give.
    """
    scan = discover_plugins(config.plugins)
    pending = [*compose_hook_section(config), *scan.pending]
    if pending:
        await asyncio.gather(*pending)
    await report_plugins(config.plugins, interface, scan)


def compose_hook_section(config: SolveigConfig) -> list[Awaitable]:
    """Give `plugins.hooks` the types the discovered hooks provide.

    The private step of `reload_plugins`, so `discover_plugins` has already run —
    this only says which types exist. Tools need no equivalent: `@tool` types its
    own entry while the scan imports it, and the scan removes the type of a tool
    whose file is gone. Hooks are the other way round — they stay plain
    callables in `HOOKS`, and `hooks_config_map` is what says which of them exist.

    Returns the async observers' coroutines the re-typing reaches, for the async
    caller to gather.

    NOTE: it lives here, above config and plugins both, because config must not
    import the plugin packages to learn what fills its own sections.
    """
    pending: list[Awaitable] = []
    live_hooks = hooks_config_map()
    # One notification for the whole re-type, like `set` gives a batch of writes.
    pending.extend(config.plugins.hooks.set_type(**dict(live_hooks)))
    gone = [name for name, _ in list(config.plugins.hooks) if name not in live_hooks]
    if gone:
        pending.extend(config.plugins.hooks.remove_type(*gone))
    return pending


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
                warnings.warn(refused)

    def _delete_subcommand(tool_cls):
        for trigger in tool_cls.subcommands:
            PLUGIN_SUBCOMMANDS.pop(trigger, None)

    @config.plugins.tools.on_change()
    async def update_subcommands_for_plugin_tools(
        _config: ConfigSection, changes: tuple[ConfigChange, ...]
    ) -> None:
        for change in changes:
            match change:
                case Created(value=entry):
                    _add_subcommand(entry.tool_class)
                case Updated(before=old, after=new):
                    _delete_subcommand(old.tool_class)
                    _add_subcommand(new.tool_class)
                case Deleted(value=entry):
                    _delete_subcommand(entry.tool_class)
