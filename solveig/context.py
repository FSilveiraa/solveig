"""Dependency-injection container passed as RunContext.deps to every tool function."""

from dataclasses import dataclass

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface


@dataclass
class SolveigContext:
    config: SolveigConfig
    interface: SolveigInterface
