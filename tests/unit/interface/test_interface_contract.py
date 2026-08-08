"""SolveigInterface contract fidelity + the protocol-level cancellation/ask
mechanics, driven through MockInterface (which implements the full surface).

Replaces the old test_group_scoping.py: that stubbed the pre-redesign ABC
(`_root`/`_display_section`/`display_text`) which no longer exists. Root-vs-group
delegation is now TerminalInterface/GroupInterface internals (the CLI layer);
what is protocol-level and worth pinning here is the interface CONTRACT itself.
"""

import asyncio
import typing
from unittest.mock import patch

import pytest

from solveig.exceptions import UserCancel
from solveig.interface.base import SolveigInterface
from solveig.interface.tui.interface import GroupInterface, TerminalInterface
from tests.mocks import MockInterface


def test_mock_interface_implements_the_whole_contract():
    """A change to the SolveigInterface ABC must fail THIS test, not silently
    leave MockInterface abstract. `__abstractmethods__` is empty iff every
    abstract method is concrete on the subclass, and the instance is real."""
    assert not MockInterface.__abstractmethods__
    assert isinstance(MockInterface(), SolveigInterface)


def test_box_contracts_are_protocols_not_silent_no_ops():
    """A missing method must fail, not return None. These are the only
    'contracts' in the project that were plain classes with empty bodies."""
    from solveig.interface.base import widgets

    for contract in (
        widgets.TextBox,
        widgets.DiffBox,
        widgets.TreeBox,
        widgets.EditableMessage,
    ):
        assert isinstance(contract, type(typing.Protocol))
        with pytest.raises(TypeError):
            contract()  # a Protocol cannot be instantiated into a no-op


def test_box_handles_inherit_their_protocol_and_are_not_widgets():
    """The three handles own a widget rather than being one.

    Both halves matter. Explicit inheritance is what moves mypy's conformance
    check to the class definition — a return-site check is only as good as the
    annotations on both sides, and that is exactly the hole `TreeBox.refresh`
    drifted through when it was widened to `(*args, **kwargs) -> object` to
    accommodate a Textual widget. Not being a `Widget` is what stops a caller
    holding a three-method `TextBox` from reaching `.mount()`, `.remove()` or
    `.parent` — the whole framework under a name that promises three methods.
    """
    from textual.widget import Widget

    from solveig.interface.base import widgets
    from solveig.interface.tui.collapsible_widgets import (
        CollapsibleDiffBox,
        CollapsibleTextBox,
    )
    from solveig.interface.tui.tree_display import FileTree

    for handle, contract in (
        (CollapsibleTextBox, widgets.TextBox),
        (CollapsibleDiffBox, widgets.DiffBox),
        (FileTree, widgets.TreeBox),
    ):
        assert issubclass(handle, contract)
        assert not issubclass(handle, Widget)


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
    and threw away a whole Textual App per tool call. The fix was structural —
    both classes now descend from the constructor-free TerminalDisplay — so the
    MRO assertion is the one that keeps it fixed.
    """
    assert TerminalInterface not in GroupInterface.__mro__

    interface = TerminalInterface()
    with patch("solveig.interface.tui.interface.SolveigTextualApp") as app_cls:
        group = GroupInterface(root=interface, group_widget=_FakeGroupWidget())
    app_cls.assert_not_called()
    assert group.app is interface.app
    assert group._active_tasks is interface._active_tasks
    assert group.user_message_queue is interface.user_message_queue


def test_cancel_hint_is_derived_from_the_bindings_that_implement_it():
    """The hint names a key, which is a promise about behaviour.

    It used to be the literal "(Esc/Ctrl+C to cancel)" passed through the
    protocol as `with_animation(suffix=...)`, and it was WRONG: Escape cancels a
    waiting prompt (`InputBar.on_key`) but never an in-flight task, which only
    `SolveigTextualApp.on_key` cancels. Deriving both from the same tuples is
    what stops the text and the handler drifting apart again.
    """
    from solveig.interface.tui import keys

    assert keys.cancel_hint(keys.TASK_CANCEL_KEYS) == "(Ctrl+C to cancel)"
    assert keys.cancel_hint(keys.PROMPT_CANCEL_KEYS) == "(Esc/Ctrl+C to cancel)"
    # A key nobody labelled still prints, rather than vanishing from the hint.
    assert keys.cancel_hint(("ctrl+q",)) == "(ctrl+q to cancel)"


def test_with_animation_takes_no_cancel_hint():
    """The protocol carries the capability, not the vocabulary. `with_cancellable`
    registering the task is what tells a frontend the work can be stopped; how a
    user reaches that is the frontend's own word."""
    import inspect

    from solveig.interface.base import SolveigInterface

    params = inspect.signature(SolveigInterface.with_animation).parameters
    assert "suffix" not in params


def test_opening_a_tool_group_passes_intent_and_reads_no_display_config():
    """`open_tool_group` used to compute `config.interface.auto_collapse_tools
    and auto_collapse` — app code reading a display setting to decide how a
    terminal draws. It now forwards the tool's own intent and nothing else; the
    frontend applies its policy at close time."""
    import inspect

    from solveig.tools import orchestration

    params = inspect.signature(orchestration.open_tool_group).parameters
    assert "config" not in params
    source = inspect.getsource(orchestration.open_tool_group)
    assert "auto_collapse_tools" not in source.split('"""')[-1]


async def test_frontend_policy_gates_the_callers_intent():
    """Both halves have to hold: a tool that opts OUT is never folded, and a
    user who turns the setting off is never overridden by a tool that opted in.

    Drives the real `with_group`, so what is asserted is the value that reaches
    `exit_group` — the frontend's decision, not a restatement of it.
    """
    from unittest.mock import AsyncMock, MagicMock

    from solveig.interface.tui.interface import TerminalInterface

    async def collapsed_with(*, tool_intent: bool, policy: bool) -> bool:
        interface = TerminalInterface.__new__(TerminalInterface)  # no Textual app
        interface._root = interface
        interface.conversation = None
        interface._active_tasks = {}
        interface.user_message_queue = None
        interface.auto_collapse_tools = policy
        area = MagicMock()
        area.enter_group = AsyncMock(return_value=_FakeGroupWidget())
        area.exit_group = AsyncMock()
        interface.app = MagicMock(_conversation_area=area)

        async with interface.with_group("t", auto_collapse=tool_intent):
            pass
        return area.exit_group.await_args.kwargs["auto_collapse"]

    assert await collapsed_with(tool_intent=True, policy=True) is True
    assert await collapsed_with(tool_intent=False, policy=True) is False  # TodoTool
    assert await collapsed_with(tool_intent=True, policy=False) is False  # the user
    assert await collapsed_with(tool_intent=False, policy=False) is False
