"""solveig.subcommand — user-invokable CLI subcommand system.

SubcommandRunner is intentionally not exported here: runner.py has deep
imports (config, sessions, mcp_servers, tools) that aren't needed by every
importer of this package.
Import it directly: ``from solveig.subcommand.runner import SubcommandRunner``
"""

from .base import Subcommand

__all__ = ["Subcommand"]
