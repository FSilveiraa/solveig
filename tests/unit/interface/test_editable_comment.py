import asyncio

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from textual.app import App, ComposeResult

from solveig.session.conversation import Conversation
from solveig.exceptions import UserCancel
from solveig.interface.cli.buttons import (
    BranchButton,
    DeleteButton,
    EditButton,
    RetryButton,
)
from solveig.interface.cli.conversation import ConversationArea
from solveig.interface.cli.widgets import EditableComment


class _StubSessionManager:
    async def store(self, conversation, name=None) -> str:
        return "stub-session.jsonl"

    async def checkpoint(self, conversation, name=None) -> str:
        return "stub-checkpoint.jsonl"


class _StubInterface:
    def __init__(self):
        self.asked = []

    @property
    def has_active_request(self) -> bool:
        # No run in flight in these tests, so the buttons' run-in-flight
        # gate always lets the action through.
        return False

    async def ask_question(self, question, default="") -> str:
        self.asked.append((question, default))
        return default

    async def notify_pending_queue_changed(self) -> None:
        pass

    async def enqueue_pending(self, text: str) -> None:
        await self.pending_queue.put(text)
        await self.notify_pending_queue_changed()


class _HarnessApp(App):
    def __init__(self, comment: EditableComment):
        super().__init__()
        self._comment = comment

    def compose(self) -> ComposeResult:
        yield self._comment


async def _conversation() -> tuple[Conversation, str, str]:
    """A two-message conversation; returns it plus the (user_id, assistant_id)."""
    conv = Conversation()
    user_id = await conv.append(ModelRequest(parts=[UserPromptPart(content="hi")]))
    assistant_id = await conv.append(ModelResponse(parts=[TextPart(content="hello")]))
    return conv, user_id, assistant_id


def _comment(conv, message_id, *, role, interface=None, session_manager=None):
    text = "hi" if role == "user" else "hello"
    return EditableComment(
        text,
        conversation=conv,
        session_manager=session_manager or _StubSessionManager(),
        interface=interface or _StubInterface(),
        message_id=message_id,
        part_index=0,
        role=role,
    )


@pytest.mark.anyio
async def test_user_message_mounts_all_four_buttons():
    conv, user_id, _ = await _conversation()
    comment = _comment(conv, user_id, role="user")
    async with _HarnessApp(comment).run_test():
        assert comment.query_one(EditButton)
        assert comment.query_one(RetryButton)
        assert comment.query_one(DeleteButton)
        assert comment.query_one(BranchButton)


@pytest.mark.anyio
async def test_assistant_message_has_no_retry_button():
    conv, _, assistant_id = await _conversation()
    comment = _comment(conv, assistant_id, role="assistant")
    async with _HarnessApp(comment).run_test():
        assert comment.query_one(EditButton)
        assert comment.query_one(DeleteButton)
        assert comment.query_one(BranchButton)
        assert len(comment.query(RetryButton)) == 0


@pytest.mark.anyio
async def test_begin_edit_updates_conversation_and_display():
    conv, user_id, _ = await _conversation()
    comment = _comment(conv, user_id, role="user")
    async with _HarnessApp(comment).run_test():
        # ask_question is stubbed to echo back the default (current text) -
        # a no-op edit round-trip through the real widget path.
        await comment.begin_edit()
        assert conv.get(user_id).parts[0].content == "hi"


@pytest.mark.anyio
async def test_delete_from_here_truncates_conversation():
    conv, _, assistant_id = await _conversation()
    comment = _comment(conv, assistant_id, role="assistant")
    async with _HarnessApp(comment).run_test():
        await comment.delete_from_here()
        assert len(conv.messages) == 1


class _CancellingInterface(_StubInterface):
    """Simulates the user pressing Escape/cancel during the edit prompt -
    ask_question raises UserCancel, as the real input_bar.py does."""

    async def ask_question(self, question, default="") -> str:
        raise UserCancel()


@pytest.mark.anyio
async def test_begin_edit_cancel_does_not_crash_or_mutate():
    """Regression: cancelling the Edit prompt used to propagate UserCancel
    unhandled up through the button's on_click, crashing the app."""
    conv, user_id, _ = await _conversation()
    comment = _comment(conv, user_id, role="user", interface=_CancellingInterface())
    async with _HarnessApp(comment).run_test():
        await comment.begin_edit()  # must not raise
        assert conv.get(user_id).parts[0].content == "hi"


class _SectionHarnessApp(App):
    def compose(self) -> ComposeResult:
        yield ConversationArea(id="conversation")


@pytest.mark.anyio
async def test_delete_click_on_nested_message_mutates_conversation():
    """Clicking Delete on a message nested inside a section container must
    truncate the conversation (the reactive transcript reconciles the widgets
    in place - no clear-from-inside-the-click-handler deadlock)."""
    conv, user_id, assistant_id = await _conversation()
    app = _SectionHarnessApp()
    async with app.run_test() as pilot:
        area = app.query_one(ConversationArea)
        session_manager = _StubSessionManager()

        await area.add_section_header("User")
        await area._add_element(
            _comment(conv, user_id, role="user", session_manager=session_manager),
            area._current_section_container,
        )
        await area.add_section_header("Assistant")
        last = _comment(
            conv, assistant_id, role="assistant", session_manager=session_manager
        )
        await area._add_element(last, area._current_section_container)
        await pilot.pause()

        # Drive the button's own click handler directly (this harness doesn't
        # load the app CSS, so pilot.click would hit-test against unstyled
        # full-width buttons). on_click defers the delete via call_after_refresh;
        # pausing lets that Screen-owned callback run the truncation.
        from textual.events import Click

        delete_btn = last.query_one(DeleteButton)
        delete_btn.on_click(
            Click(
                widget=delete_btn,
                x=0,
                y=0,
                delta_x=0,
                delta_y=0,
                button=1,
                shift=False,
                meta=False,
                ctrl=False,
            )
        )
        await asyncio.wait_for(pilot.pause(), timeout=5)
        await asyncio.wait_for(pilot.pause(), timeout=5)
        assert len(conv.messages) == 1


@pytest.mark.anyio
async def test_retry_truncates_and_requeues_prompt():
    conv, user_id, _ = await _conversation()
    interface = _StubInterface()
    interface.pending_queue = asyncio.Queue()
    comment = _comment(conv, user_id, role="user", interface=interface)
    async with _HarnessApp(comment).run_test():
        await comment.retry()
        assert len(conv.messages) == 0
        assert interface.pending_queue.get_nowait() == "hi"
