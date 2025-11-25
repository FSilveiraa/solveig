from typing import Literal

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

    async def display(self, interface: "SolveigInterface") -> None:
        """Display the assistant's message, including comment and tasks."""
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
