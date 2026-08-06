"""Statuses are a closed set with display attached - an enum, not four loose
strings shared between a Literal and a lookup table."""

from solveig.tools.core.task import Task, TaskStatus


def test_status_enum_serializes_as_its_string_for_the_llm_schema():
    task = Task(description="do it", status=TaskStatus.ONGOING)
    assert task.model_dump()["status"] == "ongoing"
    assert Task.model_validate({"description": "d", "status": "failed"}).status is (
        TaskStatus.FAILED
    )


def test_every_status_has_a_marker():
    assert {status: status.marker for status in TaskStatus}.keys() == set(TaskStatus)
