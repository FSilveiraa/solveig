"""SolveigInterface contract fidelity + the protocol-level cancellation/ask
mechanics, driven through MockInterface (which implements the full surface).

Replaces the old test_group_scoping.py: that stubbed the pre-redesign ABC
(`_root`/`_display_section`/`display_text`) which no longer exists. Root-vs-group
delegation is now TerminalInterface/GroupInterface internals (the CLI layer);
what is protocol-level and worth pinning here is the interface CONTRACT itself.
"""

import asyncio
from unittest.mock import patch

import pytest

from solveig.exceptions import UserCancel
from solveig.interface.base import SolveigInterface
from solveig.interface.cli.interface import GroupInterface, TerminalInterface
from tests.mocks import MockInterface


def test_mock_interface_implements_the_whole_contract():
    """A change to the SolveigInterface ABC must fail THIS test, not silently
    leave MockInterface abstract. `__abstractmethods__` is empty iff every
    abstract method is concrete on the subclass, and the instance is real."""
    assert not MockInterface.__abstractmethods__
    assert isinstance(MockInterface(), SolveigInterface)


async def test_ask_question_wraps_and_cleans_up_its_task():
    mi = MockInterface(user_inputs=["answer"])
    assert await mi.ask_question("Path?", default="d") == "answer"
    assert "Path?" in mi.get_all_questions()
    # the prompt-wait registered and unregistered itself
    assert mi.get_active_tasks() == {}


async def test_ask_choice_appends_cancel_and_echoes_answer():
    mi = MockInterface(choices=[0])
    # ask_choice appends a "Cancel processing" option; index 0 picks the first.
    assert await mi.ask_choice("Proceed?", ["Yes", "No"]) == 0
    assert "Yes" in mi.get_all_output()  # echoed so it lands in the caller's scope


async def test_ask_choice_cancel_index_raises_user_cancel():
    mi = MockInterface(choices=[2])  # the appended "Cancel processing" option
    with pytest.raises(UserCancel):
        await mi.ask_choice("Proceed?", ["Yes", "No"])


async def test_cancel_during_ask_question_is_translated_to_user_cancel():
    class _CancelAsk(MockInterface):
        async def _ask_question(self, question, default=""):
            raise asyncio.CancelledError()

    with pytest.raises(UserCancel):
        await _CancelAsk().ask_question("Q?")


async def test_with_cancellable_registers_and_cancel_task_reaches_it():
    mi = MockInterface()

    async def work():
        await asyncio.Event().wait()  # never completes on its own

    async with mi.with_cancellable(work(), status="working") as task:
        assert task in mi.get_active_tasks()
        assert mi.cancel_task() is True  # latest-untargeted cancel reaches it
    assert mi.get_active_tasks() == {}  # unregistered after the block


async def test_with_group_yields_the_interface_and_marks_start_end():
    mi = MockInterface()
    async with mi.with_group("g") as scoped:
        assert scoped is mi
    assert mi.groups == ["START: g", "END: g"]


async def test_add_stat_returns_a_renderable_stat():
    mi = MockInterface()
    stat = mi.add_stat("Model", get=lambda: "gpt-4o", render=lambda v: f"*{v}*")
    assert stat.text == "*gpt-4o*"
    assert stat.label == "Model"


class _FakeGroupWidget:
    """Stands in for CustomCollapsible: GroupInterface only asks it for its
    contents container."""

    def __init__(self) -> None:
        self.contents = object()

    def query_one(self, _selector):
        return self.contents


async def test_entering_a_group_builds_no_second_app():
    """A group is a scope over the root's app, not an interface that owns one.

    Pinned because GroupInterface used to inherit from the class whose
    constructor builds the app: its `super().__init__()` silently constructed
    and threw away a whole Textual App per tool call.
    """
    interface = TerminalInterface()
    with patch("solveig.interface.cli.interface.SolveigTextualApp") as app_cls:
        group = GroupInterface(root=interface, group_widget=_FakeGroupWidget())
    app_cls.assert_not_called()
    assert group.app is interface.app
    assert group._active_tasks is interface._active_tasks
