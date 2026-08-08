"""The per-message actions, from both ends of the seam.

Two halves that no longer know about each other, tested separately on purpose:

- `EditableComment` renders a control per action it was HANDED, and nothing
  else. It is given `MessageActions` directly here — there is no conversation
  in sight, which is the property worth pinning.
- the closures `SessionDisplay` builds are what actually mutate the
  conversation. They are driven through the boxes a headless MockInterface
  recorded, i.e. exactly the objects a real frontend would have clicked.
"""

import asyncio

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from textual.app import App, ComposeResult

from solveig.exceptions import UserCancel
from solveig.interface.base import MessageActions, Role
from solveig.interface.tui.buttons import (
    BranchButton,
    DeleteButton,
    EditButton,
    RetryButton,
)
from solveig.interface.tui.widgets import EditableComment
from solveig.session.conversation import Conversation
from solveig.session.display import SessionDisplay
from solveig.user_message_queue import UserMessageQueue
from tests.mocks import MockInterface


async def _drawn(
    queue: UserMessageQueue | None = None, interface: MockInterface | None = None
):
    """A two-message conversation, drawn: returns it plus the user and
    assistant boxes the interface was handed."""
    conv = Conversation()
    interface = interface or MockInterface()
    SessionDisplay(conv, interface, queue)
    await conv.append(ModelRequest(parts=[UserPromptPart(content="hi")]))
    await conv.append(ModelResponse(parts=[TextPart(content="hello")]))
    user_box, assistant_box = interface.shown
    return conv, user_box, assistant_box


class _HarnessApp(App):
    def __init__(self, comment: EditableComment):
        super().__init__()
        self._comment = comment

    def compose(self) -> ComposeResult:
        yield self._comment


def _comment(interface, actions: MessageActions, role: Role = Role.USER):
    return EditableComment("hi", interface=interface, role=role, actions=actions)


# -- the widget draws what it was handed -----------------------------------


@pytest.mark.anyio
async def test_a_button_appears_for_each_action_handed_over():
    async def _noop() -> None: ...

    comment = _comment(
        MockInterface(),
        MessageActions(
            edit=lambda text: _noop(), retry=_noop, delete=_noop, branch=_noop
        ),
    )
    async with _HarnessApp(comment).run_test():
        assert comment.query_one(EditButton)
        assert comment.query_one(RetryButton)
        assert comment.query_one(DeleteButton)
        assert comment.query_one(BranchButton)


@pytest.mark.anyio
async def test_an_action_not_handed_over_renders_no_button():
    """The widget never asks WHY retry is missing — an assistant turn is not a
    concept it knows."""

    async def _noop() -> None: ...

    comment = _comment(
        MockInterface(),
        MessageActions(edit=lambda text: _noop(), delete=_noop, branch=_noop),
        role=Role.ASSISTANT,
    )
    async with _HarnessApp(comment).run_test():
        assert comment.query_one(EditButton)
        assert len(comment.query(RetryButton)) == 0


# -- the closures do the work ----------------------------------------------


@pytest.mark.anyio
async def test_edit_rewrites_the_message_and_restates_the_box():
    conv, user_box, _ = await _drawn()

    await user_box.actions.edit("edited")

    assert conv.messages[0].parts[0].content == "edited"
    assert user_box.text == "edited"  # the transcript restated it, not the widget


@pytest.mark.anyio
async def test_begin_edit_cancel_does_not_crash_or_mutate():
    """Regression: cancelling the Edit prompt must not propagate UserCancel
    unhandled, and must leave the conversation untouched."""

    class _CancellingInterface(MockInterface):
        async def _ask_question(self, question, default=""):
            raise UserCancel()

    interface = _CancellingInterface()
    conv, user_box, _ = await _drawn(interface=interface)
    comment = _comment(interface, user_box.actions)

    await comment.begin_edit()  # must not raise

    assert conv.messages[0].parts[0].content == "hi"


@pytest.mark.anyio
async def test_delete_truncates_from_that_message():
    conv, _, assistant_box = await _drawn()

    await assistant_box.actions.delete()

    assert len(conv.messages) == 1  # the user prompt remains


@pytest.mark.anyio
async def test_retry_truncates_and_requeues_the_prompt():
    queue = UserMessageQueue()
    conv, user_box, _ = await _drawn(queue)

    await user_box.actions.retry()

    assert len(conv.messages) == 0
    assert queue.get_nowait() == "hi"


@pytest.mark.anyio
async def test_retry_resubmits_the_edited_text():
    """The text is read from the conversation when retry runs. Captured at draw
    time instead, an edit-then-retry would resend the text the user replaced."""
    queue = UserMessageQueue()
    _, user_box, _ = await _drawn(queue)

    await user_box.actions.edit("edited")
    await user_box.actions.retry()

    assert queue.get_nowait() == "edited"


@pytest.mark.anyio
async def test_retry_is_not_re_routed_through_the_subcommand_gate():
    """A retried prompt has already been through the gate once. If the registry
    gained a trigger since (a plugin reload, an MCP connect), re-gating would
    swallow the stored prompt as a command and it would simply vanish."""
    queue = UserMessageQueue()

    async def _swallow_everything(text: str) -> str | None:
        return None

    queue.prompt_handler = _swallow_everything
    _, user_box, _ = await _drawn(queue)

    await user_box.actions.retry()

    assert queue.get_nowait() == "hi"


@pytest.mark.anyio
async def test_a_mid_run_action_is_refused_by_the_closure():
    """Refusal is app policy: a rewind mid-run is reconciled away by adopt().
    The frontend is not consulted and holds no rule about it."""
    interface = MockInterface()
    conv, user_box, _ = await _drawn(interface=interface)

    async def _busy() -> None: ...

    task = asyncio.ensure_future(_busy())
    interface._active_tasks[task] = None
    try:
        await user_box.actions.delete()
    finally:
        interface._active_tasks.pop(task, None)
        await task

    assert len(conv.messages) == 2  # nothing was dropped
    assert any(
        "Finish or cancel" in str(update.get("status"))
        for update in interface.stats_updates
    )
