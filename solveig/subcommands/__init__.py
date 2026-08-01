"""solveig.subcommand — user-invokable CLI subcommand system.

Push model: every source writes its subcommands into its own store as they are
declared (the core tool list, which cannot be read until startup, is filled in
one pass then). The registry looks them up through one ordered view and
dispatches. No fetch, no iterate, no two-author split in the dispatch path.
"""

from .base import Subcommand, subcommand

__all__ = ["Subcommand", "subcommand"]
