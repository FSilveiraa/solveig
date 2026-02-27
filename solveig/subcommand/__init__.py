"""solveig.subcommand — user-invokable CLI subcommand system.

SubcommandRunner is intentionally not exported here: runner.py has deep
imports into solveig.schema which would create a circular import chain
(schema.tool.base → subcommand → runner → schema).
Import it directly: ``from solveig.subcommand.runner import SubcommandRunner``
"""

from .base import Subcommand

__all__ = ["Subcommand"]
