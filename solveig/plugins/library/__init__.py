"""The plugin library — every module here is a plugin, and nothing else is.

This package is what `discover_plugins` scans, and external directories from
`config.plugins.paths` are folded into its `__path__`, so an external plugin
imports as `solveig.plugins.library.<name>` and gets the same reload, unload and
config treatment a bundled one does.

**Nothing but plugins may live here.** The scan imports every module it finds, so
a helper dropped in this package would be loaded as a plugin. Machinery lives one
level up (`tools.py`, `hooks.py`, `subcommands.py`, `discovery.py`, `utils.py`).

A plugin declares whatever surfaces it wants — a tool, a hook, a subcommand, or
all three in one file. There is deliberately no directory per surface: which
registry a declaration lands in is decided by the decorator, never by where the
file sits.
"""
