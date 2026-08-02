"""Plugin system for Solveig.

Deliberately EMPTY, and it must stay that way. A package's `__init__` runs
whenever ANY module under it is imported, so a re-export here would put
`plugins.tools` in front of `plugins.hooks` for every importer — and
`orchestration` imports `plugins.hooks` while `plugins.tools` imports
`orchestration` back (that is how `@tool` builds a plugin tool's `/command`).

A plugin declares what it offers by importing from the module that owns that
surface, which is also what decides where the declaration lands:

    from solveig.plugins.tools import tool
    from solveig.plugins.hooks import before_tool, after_tool
    from solveig.plugins.subcommands import subcommand

Discovery and reporting live in `solveig.plugins.discovery`.
"""
