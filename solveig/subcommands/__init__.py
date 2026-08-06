"""solveig.subcommands — the user-invokable command system.

Push model: every source writes its subcommands into its own store as they are
declared (`@subcommand` here for built-ins, `solveig.plugins.subcommands` for a
plugin, `@tool` for a plugin tool). The registry looks them up through one
ordered view and dispatches.

Re-exports `subcommand` and `Subcommand` deliberately: unlike `tools`, `api`
and `interface`, this package sits entirely in one layer, so importing it as
one node merges nothing. Declare through `from solveig.subcommands import
subcommand`.
"""

from .base import Subcommand, subcommand

__all__ = ["Subcommand", "subcommand"]
