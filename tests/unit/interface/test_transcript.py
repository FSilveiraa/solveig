import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.usage import RunUsage
from textual.app import App, ComposeResult

from solveig.session.conversation import Conversation
from solveig.interface.cli.collapsible_widgets import CollapsibleTextBox
from solveig.interface.cli.conversation import ConversationArea
from solveig.interface.cli.transcript import TextualTranscript
from solveig.interface.cli.widgets import EditableComment, SectionHeader
from tests.mocks import MockInterface

pytestmark = pytest.mark.anyio


class _StubInterface:
    @property
    def has_active_request(self) -> bool:
        return False


class _StubSessionManager:
    pass


class _App(App):
    def compose(self) -> ComposeResult:
        yield ConversationArea(id="conversation")


async def _mounted(app):
    area = app.query_one(ConversationArea)
    return area, TextualTranscript(
        app._conv, area, _StubInterface(), _StubSessionManager()
    )


async def test_mount_user_and_assistant_creates_comments_with_ids_and_sections():
    conv = Conversation()
    app = _App()
    app._conv = conv
    async with app.run_test():
        area, transcript = await _mounted(app)

        uid = await conv.append(ModelRequest(parts=[UserPromptPart(content="hi")]))
        aid = await conv.append(ModelResponse(parts=[TextPart(content="hello")]))

        comments = list(app.query(EditableComment))
        assert [c.message_id for c in comments] == [uid, aid]
        assert [c.role for c in comments] == ["user", "assistant"]
        # a section header per role change
        assert len(app.query(SectionHeader)) == 2


async def test_streaming_rerender_updates_comment_content_in_place():
    conv = Conversation()
    app = _App()
    app._conv = conv
    async with app.run_test():
        area, transcript = await _mounted(app)

        await conv.begin_stream(ModelResponse(parts=[TextPart(content="Hel")]))
        comment = app.query_one(EditableComment)
        assert comment.comment == "Hel"

        await conv.stream_updated(ModelResponse(parts=[TextPart(content="Hello world")]))
        # same widget, updated content - not a second comment
        assert len(app.query(EditableComment)) == 1
        assert app.query_one(EditableComment).comment == "Hello world"


async def test_edit_rerenders_and_truncate_removes_widgets():
    conv = Conversation()
    app = _App()
    app._conv = conv
    async with app.run_test():
        area, transcript = await _mounted(app)

        a = await conv.append(ModelResponse(parts=[TextPart(content="one")]))
        b = await conv.append(ModelResponse(parts=[TextPart(content="two")]))

        await conv.edit(a, 0, "ONE")
        contents = [c.comment for c in app.query(EditableComment)]
        assert contents == ["ONE", "two"]

        await conv.truncate_from(b)
        remaining = list(app.query(EditableComment))
        assert [c.comment for c in remaining] == ["ONE"]


async def test_delete_button_click_defers_removal_and_cleans_up():
    """Clicking Delete truncates the conversation, which removes the clicked
    button's own owner widget. The button must defer that (call_after_refresh)
    rather than remove its own tree mid-click - otherwise the button is stranded
    on screen. Here we assert the deferred path actually runs the async delete:
    after the click settles, the comment (and its buttons) are gone cleanly."""
    from solveig.interface.cli.buttons import DeleteButton

    conv = Conversation()
    app = _App()
    app._conv = conv
    async with app.run_test() as pilot:
        area, transcript = await _mounted(app)

        a = await conv.append(ModelResponse(parts=[TextPart(content="one")]))
        b = await conv.append(ModelResponse(parts=[TextPart(content="two")]))

        comment_b = next(c for c in app.query(EditableComment) if c.message_id == b)
        delete_btn = comment_b.query_one(DeleteButton)

        from textual.events import Click

        click = Click(
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
        delete_btn.on_click(click)
        await pilot.pause()  # let the deferred Screen callback run the delete
        await pilot.pause()

        # b (and everything after it) is gone; a remains; no stranded buttons.
        assert [c.message_id for c in app.query(EditableComment)] == [a]
        assert conv.messages == (conv.get(a),)
        assert all(btn.owner.message_id == a for btn in app.query(DeleteButton))


async def test_reasoning_part_mounts_collapsible_box_not_comment():
    conv = Conversation()
    app = _App()
    app._conv = conv
    async with app.run_test():
        area, transcript = await _mounted(app)

        from pydantic_ai.messages import ThinkingPart

        await conv.append(
            ModelResponse(
                parts=[
                    ThinkingPart(content="planning"),
                    TextPart(content="done"),
                ]
            )
        )
        assert len(app.query(CollapsibleTextBox)) == 1
        assert [c.comment for c in app.query(EditableComment)] == ["done"]


async def test_load_replays_closed_content_and_tool_call():
    """Resume flows through the transcript (replay isn't special): load() fires
    message_added per message; closed content becomes transcript-owned widgets,
    and a tool call whose result is present replays itself via the tool."""
    conv = Conversation()
    app = _App()
    app._conv = conv
    async with app.run_test():
        area = app.query_one(ConversationArea)
        interface = MockInterface()
        TextualTranscript(conv, area, interface, _StubSessionManager())

        await conv.load(
            [
                ModelRequest(parts=[UserPromptPart(content="Review test.py")]),
                ModelResponse(
                    parts=[
                        ThinkingPart(content="I should read the file first."),
                        ToolCallPart(
                            tool_name="not_a_real_tool",
                            args={"path": "test.py"},
                            tool_call_id="call_1",
                        ),
                    ]
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="not_a_real_tool",
                            content="file contents",
                            tool_call_id="call_1",
                        )
                    ]
                ),
                ModelResponse(parts=[TextPart(content="It's safe to run.")]),
            ],
            RunUsage(),
        )

        # closed content: transcript-owned widgets (editable by id)
        comments = [c.comment for c in app.query(EditableComment)]
        assert "Review test.py" in comments
        assert "It's safe to run." in comments
        assert len(app.query(CollapsibleTextBox)) >= 1  # reasoning box
        # the tool call replayed itself (result present) via the tool's replay
        out = interface.get_all_output()
        assert "not_a_real_tool" in out
        assert "file contents" in out


async def test_live_tool_call_not_replayed_while_result_absent():
    """On a live run the tool-call message is adopted before execute() produces
    its result, so the transcript must NOT replay it (execute shows it live) -
    no double render."""
    conv = Conversation()
    app = _App()
    app._conv = conv
    async with app.run_test():
        area = app.query_one(ConversationArea)
        interface = MockInterface()
        TextualTranscript(conv, area, interface, _StubSessionManager())

        await conv.append(
            ModelResponse(
                parts=[
                    TextPart(content="let me read"),
                    ToolCallPart(
                        tool_name="not_a_real_tool", args={}, tool_call_id="c1"
                    ),
                ]
            )
        )
        assert [c.comment for c in app.query(EditableComment)] == ["let me read"]
        assert "not_a_real_tool" not in interface.get_all_output()
