"""SessionDisplay test — the one event→verb reduction a frontend sees.

Drives the REAL observer (SessionDisplay, session/display.py) headlessly through
MockInterface. This replaces the old TextualTranscript widget tests: the display
edge worth pinning is the reduction itself — which conversation event becomes
which of the three interface verbs (show_message_part / update_message /
drop_messages) — not Textual's materialization of it (interface/tui is
coverage-excluded).
"""

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

from solveig.interface.tui.conversation_area import ConversationArea
from solveig.interface.tui.message_display import MessageDisplay
from solveig.session.conversation import Conversation
from solveig.session.display import SessionDisplay
from tests.mocks import MockInterface


async def _session(conversation: Conversation) -> MockInterface:
    interface = MockInterface(conversation=conversation)
    SessionDisplay(conversation, interface)
    return interface


async def test_message_added_shows_each_part_in_order():
    conv = Conversation()
    interface = await _session(conv)

    uid = await conv.append(ModelRequest(parts=[UserPromptPart(content="hi")]))
    assert ("show", uid, 0) in interface.transcript_events
    assert interface.shown[uid] == ["hi"]

    aid = await conv.append(
        ModelResponse(parts=[ThinkingPart(content="hmm"), TextPart(content="hello")])
    )
    assert ("show", aid, 0) in interface.transcript_events  # thinking
    assert ("show", aid, 1) in interface.transcript_events  # text
    assert interface.shown[aid] == ["hmm", "hello"]


async def test_streaming_reduces_to_show_then_update():
    conv = Conversation()
    interface = await _session(conv)

    sid = await conv.begin_stream(ModelResponse(parts=[TextPart(content="Hel")]))
    assert ("show", sid, 0) in interface.transcript_events  # stream_began -> show

    await conv.stream_updated(ModelResponse(parts=[TextPart(content="Hello")]))
    assert ("update", sid) in interface.transcript_events

    await conv.finalize_stream(ModelResponse(parts=[TextPart(content="Hello")]))
    assert ("update", sid) in interface.transcript_events  # completion -> update


async def test_edit_and_truncate_map_to_update_and_drop():
    conv = Conversation()
    interface = await _session(conv)

    a = await conv.append(ModelResponse(parts=[TextPart(content="a")]))
    b = await conv.append(ModelResponse(parts=[TextPart(content="b")]))
    c = await conv.append(ModelResponse(parts=[TextPart(content="c")]))

    await conv.edit(a, 0, "A")
    assert ("update", a) in interface.transcript_events

    await conv.truncate_from(b)
    # truncated_from -> drop the tail after b in ONE batched drop
    assert any(set(ids) == {b, c} for ids in _drops(interface))
    assert set(interface.shown) == {a}


async def test_live_tool_call_shows_parts_not_replayed():
    """On a live append nothing is replayed (execute drew it live) - the parts
    are shown as-is, so there is no double render."""
    conv = Conversation()
    interface = await _session(conv)

    await conv.append(
        ModelResponse(
            parts=[
                TextPart(content="let me read"),
                ToolCallPart(tool_name="t", args={}, tool_call_id="c1"),
            ]
        )
    )
    # shown as parts, NOT re-rendered by replay
    assert any(e[0] == "show" for e in interface.transcript_events)
    assert "t" not in interface.get_all_output()


async def test_conversation_loaded_replays_recorded_tool_call():
    """Resume flows through the transcript (replay isn't special): load() fires
    conversation_loaded, which drops the current view and redraws — replaying a
    recorded tool call whose result is present via its tool, not as raw parts."""
    conv = Conversation()
    interface = await _session(conv)

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

    comments = []
    for shown in interface.shown.values():
        comments.extend(shown)
    assert "Review test.py" in comments
    assert "It's safe to run." in comments
    # the recorded tool call replayed itself (result present)
    out = interface.get_all_output()
    assert "not_a_real_tool" in out
    assert "file contents" in out


@pytest.mark.anyio
async def test_display_records_every_mounted_widget():
    """`extend` takes one iterable - `extend(*widgets)` unpacked it and tried to
    iterate a Widget. Two parts in one call is what makes the difference visible."""
    conv = Conversation()
    message_id = await conv.append(
        ModelResponse(parts=[ThinkingPart(content="hmm"), TextPart(content="hello")])
    )
    interface = MockInterface(conversation=conv)
    area = ConversationArea()
    display = MessageDisplay(conv, area, interface)

    class _HarnessApp(App):
        def compose(self) -> ComposeResult:
            yield area

    async with _HarnessApp().run_test():
        await display.display(message_id, 0, 1)

    assert len(display._mounted[message_id].widgets) == 2


@pytest.mark.anyio
async def test_a_role_change_mounts_no_header_widget():
    """Role is carried by the comment's own tint now; the section rule is gone."""
    conv = Conversation()
    user_message_id = await conv.append(
        ModelRequest(parts=[UserPromptPart(content="hi")])
    )
    assistant_message_id = await conv.append(
        ModelResponse(parts=[TextPart(content="hello")])
    )
    interface = MockInterface(conversation=conv)
    area = ConversationArea()
    display = MessageDisplay(conv, area, interface)

    class _HarnessApp(App):
        def compose(self) -> ComposeResult:
            yield area

    async with _HarnessApp().run_test():
        await display.display(user_message_id, 0)
        await display.display(assistant_message_id, 0)

        assert all(type(w).__name__ != "SectionHeader" for w in area.children)

    assert len(display._mounted[user_message_id].widgets) == 1
    assert len(display._mounted[assistant_message_id].widgets) == 1


def _drops(interface: MockInterface):
    """The ids-tuples of every drop event."""
    return [e[1] for e in interface.transcript_events if e[0] == "drop"]
