"""Dependency-injection container passed as RunContext.deps to every tool function."""

from dataclasses import dataclass

from pydantic_ai import RunContext

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface


@dataclass
class SolveigDeps:
    config: SolveigConfig
    interface: SolveigInterface


# Every tool/hook/capability in Solveig is typed against this one RunContext
# shape - `SolveigContext` is just a shorter name for it.
SolveigContext = RunContext[SolveigDeps]
