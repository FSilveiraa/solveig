"""The plugin-facing `@subcommand` decorator.

A plugin is not required to be a tool. `/weather london` may be worth writing
with none of a tool's machinery — no LLM schema, no consent posture, no
`ToolResult` — and a plugin author gets there by importing `subcommand` from
`solveig.plugins`, exactly as they import `tool` and `before`/`after`.

**Why a second decorator rather than an argument.** Where a declaration LANDS is
decided by which decorator was imported. A plugin's commands must share the
plugin lifecycle — replaced wholesale on reload, withdrawn when the file is
deleted, ranked below the built-ins that own `/config` and `/help` — and the
built-in decorator has none of that. Passing a target (`@subcommand("/x",
store=…)`) would put a silent, forgettable argument between a plugin and its own
lifecycle; deriving one from `fn.__module__` would re-encode structure as text.
Importing from the plugin package is a reference, and it is the convention every
other plugin surface already follows.

There is no separate inbox: the decorator writes into `PLUGIN_SUBCOMMANDS` as it
runs, which happens while the rescan imports the module. `clear()` before that
rescan is what makes a reload replace rather than accumulate — the same job
`clear_tools()` does, and it empties the store for plugin TOOL commands too,
since `@tool` writes to the same place.
"""

from solveig.subcommands.base import PLUGIN_SUBCOMMANDS, declaring_into

subcommand = declaring_into(PLUGIN_SUBCOMMANDS)


def clear_subcommands() -> None:
    """Drop every plugin-contributed subcommand — both `@subcommand` functions
    and `@tool` tools' commands — before a rescan, and in tests."""
    PLUGIN_SUBCOMMANDS.clear()


__all__ = ["subcommand", "clear_subcommands"]
