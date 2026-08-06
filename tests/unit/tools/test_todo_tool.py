"""Statuses are a closed set with display attached - an enum, not four loose
strings shared between a Literal and a lookup table - and the tool hands the list
over as values rather than as drawn text."""

from solveig.todo import TodoItem, TodoStatus
from solveig.tools.core.todo import TodoTool
from tests.mocks import DEFAULT_CONFIG, MockInterface


def test_status_enum_serializes_as_its_string_for_the_llm_schema():
    todo = TodoItem(content="do it", status=TodoStatus.IN_PROGRESS)
    assert todo.model_dump()["status"] == "in_progress"
    assert TodoItem.model_validate({"content": "d", "status": "cancelled"}).status is (
        TodoStatus.CANCELLED
    )


def test_every_status_has_a_marker():
    assert {status: status.marker for status in TodoStatus}.keys() == set(TodoStatus)


def test_the_llm_facing_name_is_the_industry_one():
    """`todo`, `todos`, `content` and the status values are what Claude Code,
    gemini-cli, qwen-code and Hermes all present to a model. A model is better at a
    tool whose vocabulary matches what it has seen everywhere else, so these names
    are not ours to prefer differently."""
    assert TodoTool.tool_name() == "todo"
    assert "todos" in TodoTool.model_fields
    assert "content" in TodoItem.model_fields
    assert {s.value for s in TodoStatus} == {
        "pending",
        "in_progress",
        "completed",
        "cancelled",
    }


async def test_execute_hands_over_values_not_drawn_text():
    """The tool must not decide that the current item is an arrow: a frontend that
    animates it instead would have no way to disagree once this is a string."""
    interface = MockInterface()
    todos = [
        TodoItem(content="first", status=TodoStatus.COMPLETED),
        TodoItem(content="second", status=TodoStatus.IN_PROGRESS),
    ]

    await TodoTool(todos=todos).execute(DEFAULT_CONFIG, interface)

    assert interface.todos == todos
    assert not any("→" in line for line in interface.outputs), interface.outputs
    assert not any("🔵" in line for line in interface.outputs), interface.outputs
