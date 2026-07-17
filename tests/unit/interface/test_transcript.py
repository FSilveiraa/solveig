import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from textual.app import App, ComposeResult

from solveig.conversation import Conversation
from solveig.interface.cli.collapsible_widgets import CollapsibleTextBox
from solveig.interface.cli.conversation import ConversationArea
from solveig.interface.cli.transcript import TextualTranscript
from solveig.interface.cli.widgets import EditableComment, SectionHeader

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

        live = ModelResponse(parts=[TextPart(content="Hel")])
        await conv.begin_stream(live)
        comment = app.query_one(EditableComment)
        assert comment.comment == "Hel"

        live.parts[0].content = "Hello world"
        await conv.stream_updated()
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
