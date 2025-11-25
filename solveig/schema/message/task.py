from typing import Literal

from pydantic import BaseModel, Field


# Define statuses and their corresponding emojis
TASK_STATUS_MAP = {
    "pending": "⚪",
    "ongoing": "🔵",
    "completed": "🟢",
    "failed": "🔴",
}
# TaskStatus = Literal[tuple(TASK_STATUS_MAP.keys())]


class Task(BaseModel):
    """Individual task item with minimal fields for LLM JSON generation."""

    description: str = Field(
        ..., description="Clear description of what needs to be done"
    )
    status: Literal["pending", "ongoing", "completed", "failed"] = Field(
        default="pending", description="Current status of this task"
    )
