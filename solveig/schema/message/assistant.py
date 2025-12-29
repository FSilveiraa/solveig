from typing import Any, Literal

from pydantic import Field

from solveig.interface import SolveigInterface
from solveig.schema import Requirement
from solveig.schema.message.base import BaseMessage
from solveig.schema.message.task import TASK_STATUS_MAP, Task


class AssistantMessage(BaseMessage):
    """Assistant message containing a comment and optionally a task plan and a list of required operations"""

    role: Literal["assistant"] = "assistant"
    comment: str = Field(..., description="Conversation with user and plan description")
    tasks: list[Task] | None = Field(
        None, description="List of tasks to track and display"
    )
    requirements: list[Requirement] | None = (
        None  # Simplified - actual schema generated dynamically
    )
    # Store reasoning content and details from o1/o3/Gemini models
    # Note: we don't communicate these fields to the LLM in the response model
    reasoning: str | None = Field(
        default=None, exclude=True, description="Reasoning text from o1/o3 models"
    )
    reasoning_details: list[dict[str, Any]] | None = Field(
        default=None, exclude=True, description="Reasoning details from API response"
    )

    def to_openai(self) -> dict:
        """Override to include reasoning_details for OpenRouter Gemini compatibility."""
        result = super().to_openai()
        # Add reasoning_details at message level (not in content) if present
        if self.reasoning_details:
            result["reasoning_details"] = self.reasoning_details
        return result

    async def display(self, interface: "SolveigInterface") -> None:
        """Display the assistant's message, including reasoning, comment and tasks."""
        # Display reasoning before the comment (o1/o3 models)
        if self.reasoning:
            await interface.display_text_block(self.reasoning, title="Reasoning")

        if self.comment:
            await interface.display_comment(self.comment)

        if self.tasks:
            task_lines = []
            for i, task in enumerate(self.tasks, 1):
                status_emoji = TASK_STATUS_MAP[task.status]
                task_lines.append(
                    f"{'→' if task.status == 'ongoing' else ' '}  {status_emoji} {i}. {task.description}"
                )

            async with interface.with_group("Tasks"):
                for line in task_lines:
                    await interface.display_text(line)
