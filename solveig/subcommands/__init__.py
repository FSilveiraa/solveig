"""solveig.subcommand — user-invokable CLI subcommand system.

Push model: every subcommand source pushes into _PENDING at import time.
The registry reads the list, binds handlers, and dispatches. No fetch,
no iterate, no two-author split in the dispatch path.
"""

from .base import Subcommand, subcommand

__all__ = ["Subcommand", "subcommand"]
