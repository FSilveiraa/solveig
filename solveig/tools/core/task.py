"""Task tool - lets the assistant display/update a tracked task plan.

Task-as-tool-call, not a response-schema field: under native tool-calling
there's no single JSON blob to hang a `tasks` field off of, so tracking a
task plan is just another tool the assistant calls whenever it wants to
show/update one - same shape as every other tool.
"""

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from solveig.tools.base import BaseTool
from solveig.tools.result import ToolResult

if TYPE_CHECKING:
    from solveig.config import SolveigConfig
    from solveig.interface import SolveigInterface

TASK_STATUS_MAP = {
    "pending": "⚪",
    "ongoing": "🔵",
    "completed": "🟢",
    "failed": "🔴",
}


class Task(BaseModel):
    """Individual task item with minimal fields for LLM JSON generation."""

    description: str = Field(
        ..., description="Clear description of what needs to be done"
    )
    status: Literal["pending", "ongoing", "completed", "failed"] = Field(
        default="pending", description="Current status of this task"
    )


class TasksTool(BaseTool):
    """Display the current task plan, replacing whatever was shown before."""

    tasks: list[Task] = Field(
        description=(
            "The full current list of tasks, in order, each with its status. "
            "Always send the complete list, not just what changed."
        )
    )

    @property
    def title(self) -> str:
        return "Tasks"

    async def execute(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> ToolResult:
        for i, task in enumerate(self.tasks, 1):
            status_emoji = TASK_STATUS_MAP[task.status]
            arrow = "→" if task.status == "ongoing" else " "
            await interface.display_text(
                f"{arrow}  {status_emoji} {i}. {task.description}"
            )
        return ToolResult(content=f"Displayed {len(self.tasks)} task(s).")
