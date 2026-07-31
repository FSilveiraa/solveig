"""
Solveig: A safe bridge between AI assistants and your computer.

This package provides a security-focused interface that translates
LLM responses into structured requests (file operations and shell commands)
that require explicit user approval before execution.
"""

__version__ = "0.1.0"
__author__ = "Francisco"
__license__ = "MIT"

# Deliberately re-exports nothing but the metadata above: the root package is
# imported by everything, so re-exporting Client here would drag the whole
# provider + interface stack into `import solveig.config`. Import from the real
# module (`solveig.config`, `solveig.api.client`, ...).

__all__ = ["__version__"]
