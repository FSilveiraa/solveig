"""EditableComment widget tests — the per-message action buttons.

The action methods (edit / retry / delete) run headlessly through MockInterface
(conversation-bound): they mutate the Conversation by id, exactly as the real
widget path does, with no Textual App needed. Only the two button-MOUNT tests
spin up the App, to assert which buttons render for which role. (The old
section-container harness was deleted with section machinery.)
"""

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from textual.app import App, ComposeResult

from solveig.exceptions import UserCancel
from solveig.interface.base import Role
from solveig.interface.tui.buttons import (
    BranchButton,
    DeleteButton,
    EditButton,
    RetryButton,
)
from solveig.interface.tui.widgets import EditableComment
from solveig.session.conversation import Conversation
from solveig.user_message_queue import UserMessageQueue
from tests.mocks import MockInterface


async def _conversation() -> tuple[Conversation, str, str]:
    """A two-message conversation; returns it plus (user_id, assistant_id)."""
    conv = Conversation()
    user_id = await conv.append(ModelRequest(parts=[UserPromptPart(content="hi")]))
    assistant_id = await conv.append(ModelResponse(parts=[TextPart(content="hello")]))
    return conv, user_id, assistant_id


def _comment(conv, message_id, *, role: Role, interface=None):
    return EditableComment(
        "hi" if role is Role.USER else "hello",
        conversation=conv,
        interface=interface or MockInterface(conversation=conv),
        message_id=message_id,
        part_index=0,
        role=role,
    )


class _HarnessApp(App):
    def __init__(self, comment: EditableComment):
        super().__init__()
        self._comment = comment

    def compose(self) -> ComposeResult:
        yield self._comment


@pytest.mark.anyio
async def test_user_message_mounts_edit_retry_delete_branch():
    conv, user_id, _ = await _conversation()
    comment = _comment(conv, user_id, role=Role.USER)
    async with _HarnessApp(comment).run_test():
        assert comment.query_one(EditButton)
        assert comment.query_one(RetryButton)
        assert comment.query_one(DeleteButton)
        assert comment.query_one(BranchButton)


@pytest.mark.anyio
async def test_assistant_message_has_no_retry_button():
    conv, _, assistant_id = await _conversation()
    comment = _comment(conv, assistant_id, role=Role.ASSISTANT)
    async with _HarnessApp(comment).run_test():
        assert comment.query_one(EditButton)
        assert comment.query_one(DeleteButton)
        assert comment.query_one(BranchButton)
        assert len(comment.query(RetryButton)) == 0


@pytest.mark.anyio
async def test_begin_edit_updates_conversation_and_display():
    conv, user_id, _ = await _conversation()
    interface = MockInterface(conversation=conv, user_inputs=["edited"])
    comment = _comment(conv, user_id, role=Role.USER, interface=interface)

    await comment.begin_edit()

    assert comment.comment == "edited"
    assert conv.get(user_id).parts[0].content == "edited"


@pytest.mark.anyio
async def test_delete_from_here_truncates_conversation():
    conv, _, assistant_id = await _conversation()
    comment = _comment(conv, assistant_id, role=Role.ASSISTANT)

    await comment.delete_from_here()

    assert len(conv.messages) == 1  # the user prompt remains


class _CancellingInterface(MockInterface):
    """The user pressed Escape during the edit prompt - ask_question raises
    UserCancel, as the real input path does."""

    async def _ask_question(self, question, default=""):
        raise UserCancel()


@pytest.mark.anyio
async def test_begin_edit_cancel_does_not_crash_or_mutate():
    """Regression: cancelling the Edit prompt must not propagate UserCancel
    unhandled, and must leave the conversation untouched."""
    conv, user_id, _ = await _conversation()
    comment = _comment(conv, user_id, role=Role.USER, interface=_CancellingInterface())

    await comment.begin_edit()  # must not raise

    assert conv.get(user_id).parts[0].content == "hi"


@pytest.mark.anyio
async def test_retry_truncates_and_requeues_prompt():
    conv, user_id, _ = await _conversation()
    interface = MockInterface(conversation=conv)
    interface.user_message_queue = UserMessageQueue()
    comment = _comment(conv, user_id, role=Role.USER, interface=interface)

    await comment.retry()

    assert len(conv.messages) == 0  # truncated
    assert interface.user_message_queue.get_nowait() == "hi"
