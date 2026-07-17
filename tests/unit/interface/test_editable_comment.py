import asyncio

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from textual.app import App, ComposeResult

from solveig.conversation import Conversation
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

    async def redraw(self, conversation, interface) -> None:
        pass


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

    async def clear_conversation(self) -> None:
        pass

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


def _conversation() -> Conversation:
    return Conversation(
        messages=[
            ModelRequest(parts=[UserPromptPart(content="hi")]),
            ModelResponse(parts=[TextPart(content="hello")]),
        ]
    )


@pytest.mark.anyio
async def test_user_message_mounts_all_four_buttons():
    comment = EditableComment(
        "hi",
        conversation=_conversation(),
        session_manager=_StubSessionManager(),
        interface=_StubInterface(),
        msg_index=0,
        part_index=0,
        role="user",
    )
    async with _HarnessApp(comment).run_test():
        assert comment.query_one(EditButton)
        assert comment.query_one(RetryButton)
        assert comment.query_one(DeleteButton)
        assert comment.query_one(BranchButton)


@pytest.mark.anyio
async def test_assistant_message_has_no_retry_button():
    comment = EditableComment(
        "hello",
        conversation=_conversation(),
        session_manager=_StubSessionManager(),
        interface=_StubInterface(),
        msg_index=1,
        part_index=0,
        role="assistant",
    )
    async with _HarnessApp(comment).run_test():
        assert comment.query_one(EditButton)
        assert comment.query_one(DeleteButton)
        assert comment.query_one(BranchButton)
        assert len(comment.query(RetryButton)) == 0


@pytest.mark.anyio
async def test_begin_edit_updates_conversation_and_display():
    conversation = _conversation()
    comment = EditableComment(
        "hi",
        conversation=conversation,
        session_manager=_StubSessionManager(),
        interface=_StubInterface(),
        msg_index=0,
        part_index=0,
        role="user",
    )
    async with _HarnessApp(comment).run_test():
        # ask_question is stubbed to echo back the default (current text) -
        # simulates a no-op edit round-trip through the real widget path.
        await comment.begin_edit()
        assert conversation.messages[0].parts[0].content == "hi"


@pytest.mark.anyio
async def test_delete_from_here_truncates_conversation():
    conversation = _conversation()
    comment = EditableComment(
        "hi",
        conversation=conversation,
        session_manager=_StubSessionManager(),
        interface=_StubInterface(),
        msg_index=1,
        part_index=0,
        role="assistant",
    )
    async with _HarnessApp(comment).run_test():
        await comment.delete_from_here()
        assert len(conversation.messages) == 1


class _CancellingInterface(_StubInterface):
    """Simulates the user pressing Escape/cancel during the edit prompt -
    ask_question raises UserCancel, as the real input_bar.py does."""

    async def ask_question(self, question, default="") -> str:
        raise UserCancel()


@pytest.mark.anyio
async def test_begin_edit_cancel_does_not_crash_or_mutate():
    """Regression test: cancelling the Edit prompt used to propagate
    UserCancel unhandled up through the button's on_click, crashing the
    app - every other ask_question call site catches it."""
    conversation = _conversation()
    comment = EditableComment(
        "hi",
        conversation=conversation,
        session_manager=_StubSessionManager(),
        interface=_CancellingInterface(),
        msg_index=0,
        part_index=0,
        role="user",
    )
    async with _HarnessApp(comment).run_test():
        await comment.begin_edit()  # must not raise
        assert conversation.messages[0].parts[0].content == "hi"


class _RealClearInterface(_StubInterface):
    """Unlike _StubInterface, actually clears the mounted ConversationArea -
    needed to reproduce the deadlock where clicking a button removes an
    ancestor of the widget whose click handler is still running."""

    def __init__(self, app: App):
        super().__init__()
        self.app = app

    async def clear_conversation(self) -> None:
        await self.app.query_one(ConversationArea).clear()


class _SectionHarnessApp(App):
    def compose(self) -> ComposeResult:
        yield ConversationArea(id="conversation")


@pytest.mark.anyio
async def test_delete_click_on_nested_message_does_not_deadlock_app():
    """Regression test: clicking Delete on a message that's nested inside a
    section container (as every real display_comment call produces) used to
    hang forever - clear_conversation() removed the button's own ancestor
    chain from inside that same click handler's call stack, deadlocking
    Textual's message pump. If this regresses, the test times out instead
    of hanging the suite."""
    conversation = _conversation()
    app = _SectionHarnessApp()
    async with app.run_test() as pilot:
        area = app.query_one(ConversationArea)
        interface = _RealClearInterface(app)
        session_manager = _StubSessionManager()

        await area.add_section_header("User")
        await area._add_element(
            EditableComment(
                "hi",
                conversation=conversation,
                session_manager=session_manager,
                interface=interface,
                msg_index=0,
                part_index=0,
                role="user",
            ),
            area._current_section_container,
        )
        await area.add_section_header("Assistant")
        last = EditableComment(
            "hello",
            conversation=conversation,
            session_manager=session_manager,
            interface=interface,
            msg_index=1,
            part_index=0,
            role="assistant",
        )
        await area._add_element(last, area._current_section_container)
        await pilot.pause()

        await asyncio.wait_for(pilot.click(last.query_one(DeleteButton)), timeout=5)
        # The app must still be responsive after the click - this would
        # hang forever before the fix.
        await asyncio.wait_for(pilot.pause(), timeout=5)
        assert len(conversation.messages) == 1


@pytest.mark.anyio
async def test_retry_truncates_and_requeues_prompt():
    conversation = _conversation()
    interface = _StubInterface()
    interface.pending_queue = asyncio.Queue()
    comment = EditableComment(
        "hi",
        conversation=conversation,
        session_manager=_StubSessionManager(),
        interface=interface,
        msg_index=0,
        part_index=0,
        role="user",
    )
    async with _HarnessApp(comment).run_test():
        await comment.retry()
        assert len(conversation.messages) == 0
        assert interface.pending_queue.get_nowait() == "hi"
