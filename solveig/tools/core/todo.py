"""Todo tool — the surface through which the assistant edits Solveig's todo list.

Todo-as-tool-call, not a response-schema field: under native tool-calling there's no
single JSON blob to hang a `todos` field off of, so tracking the list is just another
tool the assistant calls whenever it wants to show or update one — same shape as
every other tool.

The list itself is not this module's: `TodoItem`/`TodoStatus` live at layer 0 in
`solveig.todo`, so a frontend can be handed them without depending on `solveig.tools`.
"""

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

from solveig.todo import TodoItem
from solveig.tools.base import BaseTool
from solveig.tools.result import ToolResult

if TYPE_CHECKING:
    from solveig.config import SolveigConfig
    from solveig.interface.base import SolveigInterface


class TodoTool(BaseTool):
    """Display the current todo list, replacing whatever was shown before."""

    # The list is the point of the call and stays readable after it finishes.
    auto_collapse: ClassVar[bool] = False

    todos: list[TodoItem] = Field(
        description=(
            "The full current list of todos, in order, each with its status. "
            "Always send the complete list, not just what changed. "
            "Only one todo should be in_progress at a time."
        )
    )

    @property
    def title(self) -> str:
        return "Todo"

    async def execute(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> ToolResult:
        # NOTE: the tool decides WHAT to show and WHEN; the frontend decides how it
        # looks. A terminal draws a marker and an arrow, a web UI may animate the
        # in-progress item instead — neither is expressible once this is a string.
        await interface.display_todos(self.todos)
        return ToolResult(content=f"Displayed {len(self.todos)} todo(s).")
