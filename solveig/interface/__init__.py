"""
Interface layer for Solveig - handles all user interaction and presentation.
"""

from .base import RequirementPresentation, SolveigInterface
from .cli import CLIInterface

__all__ = ["SolveigInterface", "RequirementPresentation", "CLIInterface"]
