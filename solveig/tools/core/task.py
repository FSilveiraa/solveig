"""Task tool - lets the assistant display/update a tracked task plan.

Task-as-tool-call, not a response-schema field: under native tool-calling
there's no single JSON blob to hang a `tasks` field off of, so tracking a
task plan is just another tool the assistant calls whenever it wants to
show/update one - same shape as every other tool.
"""

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from solveig.context import SolveigContext
from solveig.tools.result import ToolResult

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


async def update_tasks(
    ctx: RunContext[SolveigContext],
    tasks: list[Task],
) -> ToolResult:
    """Display the current task plan, replacing whatever was shown before.

    Args:
        tasks: The full current list of tasks, in order, each with its status.
            Always send the complete list, not just what changed.
    """
    interface = ctx.deps.interface
    async with interface.with_group("Tasks"):
        for i, task in enumerate(tasks, 1):
            status_emoji = TASK_STATUS_MAP[task.status]
            arrow = "→" if task.status == "ongoing" else " "
            await interface.display_text(
                f"{arrow}  {status_emoji} {i}. {task.description}"
            )

    return ToolResult(content=f"Displayed {len(tasks)} task(s).")
