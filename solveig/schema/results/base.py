from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field

from ..base import BaseSolveigModel

# Circular import fix:
# - This module (base.py) needs Requirement classes for type hints
# - requirement.py imports Result classes for actual usage
# - TYPE_CHECKING solves this: imports are only loaded during type checking,
#   not at runtime, breaking the circular dependency
if TYPE_CHECKING:
    from ..requirements import Requirement


class RequirementResult(BaseSolveigModel):
    # we store the initial requirement for debugging/error printing,
    # then when JSON'ing we usually keep a couple of its fields in the result's body
    # We keep paths separately from the requirement, since we want to preserve both the path(s) the LLM provided
    # and their absolute value (~/Documents vs /home/jdoe/Documents)
    requirement: Requirement = Field(exclude=True)
    accepted: bool
    error: str | None = None

    def to_openai(self):
        return self.model_dump()
