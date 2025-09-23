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
    title: Literal["task list"] = "task list"
    tasks: list[Task] = Field(
        default_factory=list, description="List of tasks to track and display"
    )

    def display_header(
        self, interface: "SolveigInterface", detailed: bool = False
    ) -> None:
        """Display task list header."""
        super().display_header(interface)
        if detailed:
            if not self.tasks:
                interface.display_text("🗒 Empty task list")
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
                interface.display_text(line)

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
        return "task(tasks): use to break down your plan into sorted actions. Update status as you progress. Condense completed task lists when starting new ones."

    def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "TaskListResult":
        """Task lists don't need user approval - just display and return."""
        # No user approval needed - this is just informational
        # The display already happened in display_header()
        return TaskListResult(accepted=True, tasks=self.tasks, requirement=self)
