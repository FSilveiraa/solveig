"""Task requirement - allows LLM to create and track task lists."""

from typing import TYPE_CHECKING, Literal

from pydantic import Field

from .base import Requirement

if TYPE_CHECKING:
    from solveig.config import SolveigConfig
    from solveig.interface import SolveigInterface
    from solveig.schema.results import TaskListResult
    from solveig.schema.results.task import Task
else:
    from solveig.schema.results import TaskListResult
    from solveig.schema.results.task import Task


class TaskListRequirement(Requirement):
    title: Literal["tasks"] = "tasks"
    comment: str = Field(..., description="Conversation with user and plan description")
    tasks: list[Task] | None = Field(
        None, description="List of tasks to track and display"
    )

    async def display_header(self, interface: "SolveigInterface") -> None:
        """Display task list header."""
        await super().display_header(interface)
        if not self.tasks:
            # await interface.display_text("🗒 Empty task list")
            return

        task_lines = []
        for i, task in enumerate(self.tasks, 1):
            status_emoji = {
                "pending": "⚪",
                "in_progress": "🔵",
                "completed": "🟢",
                "failed": "🔴",
            }[task.status]
            task_lines.append(
                f"{"→" if task.status == "in_progress" else " "}  {status_emoji} {i}. {task.description}"
            )

        # interface.show("🗒 Task List")
        for line in task_lines:
            await interface.display_text(line)

    def create_error_result(
        self, error_message: str, accepted: bool
    ) -> "TaskListResult":
        """Create TaskResult with error (though tasks rarely error)."""
        return TaskListResult(
            requirement=self, accepted=accepted, error=error_message, tasks=self.tasks
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of task capability."""
        return "tasks(comment, tasks=null): use to communicate with user and break down your plan into sorted actions. Use tasks only if plan requires multiple steps, update status as you progress and condense completed task lists when starting new ones."

    async def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "TaskListResult":
        """Task lists don't need user approval - just display and return."""
        # No user approval needed - this is just informational
        # The display already happened in display_header()
        return TaskListResult(accepted=True, tasks=self.tasks, requirement=self)
