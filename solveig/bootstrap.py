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
from config.editor import prompt_for_field
from solveig.exceptions import UserCancel
from solveig.interface.base import SolveigInterface, Stat
from solveig.plugins.config import PluginToolsConfig, PluginHooksConfig
from solveig.plugins.discovery import ON_SCANNED, discover_plugins, report_plugins
from solveig.plugins.hooks import hooks_config_map
from solveig.plugins.tools import PLUGIN_TOOLS, config_model_of, plugin_tool_name


# TODO: delete, `compose()` is getting deleted, replace with
#  `plugin_tools_config.set({tool.name for tool in ...})`
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
    PluginToolsConfig.compose({
        plugin_tool_name(e): config_model_of(e)
        for e in PLUGIN_TOOLS
    })
    PluginHooksConfig.compose(hooks_config_map())


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
    # compose_plugin_sections() itself rebuilds every live instance now, so
    # there is nothing left to do here.
    discover_plugins(config.plugins.paths)

    # NOTE: nothing re-registers subcommands here. `discover_plugins` empties the
    # plugin store before the rescan, and every `@tool`/`@subcommand` in a
    # scanned module refills it on import - so a plugin deleted from disk loses
    # its command by simply never declaring it again.
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
