"""Task tool - lets the assistant display/update a tracked task plan.

Task-as-tool-call, not a response-schema field: under native tool-calling
there's no single JSON blob to hang a `tasks` field off of, so tracking a
task plan is just another tool the assistant calls whenever it wants to
show/update one - same shape as every other tool.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, Field

from solveig.tools.base import BaseTool
from solveig.tools.result import ToolResult

if TYPE_CHECKING:
    from solveig.config import SolveigConfig
    from solveig.interface.base import SolveigInterface


class TaskStatus(StrEnum):
    """A task's state, and how it is drawn.

    A StrEnum so the LLM schema still shows plain strings ("pending",
    "ongoing", ...) while the codebase addresses members. The marker is a
    member attribute rather than a dict keyed by the same four strings a
    second time - a status and its icon are declared once, together.
    """

    marker: str

    def __new__(cls, value: str, marker: str) -> "TaskStatus":
        # NOTE: StrEnum's own __new__ concatenates every argument into the
        # value, so a member carrying a second attribute has to build the str
        # itself and keep `_value_` the bare name the LLM sees.
        status = str.__new__(cls, value)
        status._value_ = value
        status.marker = marker
        return status

    PENDING = ("pending", "⚪")
    ONGOING = ("ongoing", "🔵")
    COMPLETED = ("completed", "🟢")
    FAILED = ("failed", "🔴")


class Task(BaseModel):
    """Individual task item with minimal fields for LLM JSON generation."""

    description: str = Field(
        ..., description="Clear description of what needs to be done"
    )
    status: TaskStatus = Field(
        default=TaskStatus.PENDING, description="Current status of this task"
    )


class TasksTool(BaseTool):
    """Display the current task plan, replacing whatever was shown before."""

    # The plan is the point of the call and stays readable after it finishes.
    auto_collapse: ClassVar[bool] = False

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
            arrow = "→" if task.status is TaskStatus.ONGOING else " "
            await interface.print(
                f"{arrow}  {task.status.marker} {i}. {task.description}"
            )
        return ToolResult(content=f"Displayed {len(self.tasks)} task(s).")
