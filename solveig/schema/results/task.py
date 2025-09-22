from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .base import RequirementResult


class Task(BaseModel):
    """Individual task item with minimal fields for LLM JSON generation."""

    description: str = Field(
        ..., description="Clear description of what needs to be done"
    )
    status: Literal["pending", "in_progress", "completed", "failed"] = Field(
        default="pending", description="Current status of this task"
    )


class TaskListResult(RequirementResult):
    """Result of a task requirement - just echoes the task list back to LLM."""

    tasks: list[Task] = []
