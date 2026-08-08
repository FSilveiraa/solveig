"""SessionDisplay test — the one event→verb reduction a frontend sees.

Drives the REAL observer (SessionDisplay, session/display.py) headlessly through
MockInterface. The display edge worth pinning is the reduction itself — which
conversation event becomes which of the two interface verbs (add_message /
add_reasoning) and which handle call — not Textual's materialization of it
(interface/tui is coverage-excluded).

What the assertions deliberately never touch: a message id. The mock has no way
to reach one, which is the property this seam exists to have.
"""

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

from solveig.interface.base import Role
from solveig.session.conversation import Conversation
from solveig.session.display import SessionDisplay
from tests.mocks import MockInterface


async def _session(conversation: Conversation) -> MockInterface:
    interface = MockInterface()
    SessionDisplay(conversation, interface)
    return interface


def _texts(interface: MockInterface) -> list[str]:
    return [box.text for box in interface.shown]


async def test_message_added_draws_each_part_in_order():
    conv = Conversation()
    interface = await _session(conv)

    await conv.append(ModelRequest(parts=[UserPromptPart(content="hi")]))
    assert _texts(interface) == ["hi"]
    assert interface.shown[0].role is Role.USER

    await conv.append(
        ModelResponse(parts=[ThinkingPart(content="hmm"), TextPart(content="hello")])
    )
    assert _texts(interface) == ["hi", "hmm", "hello"]
    # reasoning is its own verb, and carries no role
    assert ("reasoning", "hmm") in interface.transcript_events
    assert interface.shown[1].role is None
    assert interface.shown[2].role is Role.ASSISTANT


async def test_streaming_replaces_through_the_handle():
    """A stream must not redraw: the first token adds a box, every token after
    restates THAT box."""
    conv = Conversation()
    interface = await _session(conv)

    await conv.begin_stream(ModelResponse(parts=[TextPart(content="Hel")]))
    box = interface.shown[0]
    assert box.text == "Hel"

    await conv.stream_updated(ModelResponse(parts=[TextPart(content="Hello")]))
    await conv.finalize_stream(ModelResponse(parts=[TextPart(content="Hello!")]))

    assert interface.shown == [box]  # same handle throughout
    assert box.text == "Hello!"


async def test_edit_restates_and_truncate_removes_the_tail():
    conv = Conversation()
    interface = await _session(conv)

    a = await conv.append(ModelResponse(parts=[TextPart(content="a")]))
    b = await conv.append(ModelResponse(parts=[TextPart(content="b")]))
    await conv.append(ModelResponse(parts=[TextPart(content="c")]))
    first, second, third = interface.shown

    await conv.edit(a, 0, "A")
    assert first.text == "A"

    await conv.truncate_from(b)
    assert interface.shown == [first]
    assert (second.removed, third.removed) == (True, True)


async def test_only_a_user_turn_is_offered_retry():
    """The rule lives in the closures, so an assistant message simply arrives
    without a retry action and no frontend renders a button for it."""
    conv = Conversation()
    interface = await _session(conv)

    await conv.append(ModelRequest(parts=[UserPromptPart(content="hi")]))
    await conv.append(ModelResponse(parts=[TextPart(content="hello")]))
    user_box, assistant_box = interface.shown

    assert user_box.offered == {"edit", "retry", "delete", "branch"}
    assert assistant_box.offered == {"edit", "delete", "branch"}


async def test_live_tool_call_is_not_replayed():
    """On a live append nothing is replayed (execute drew it live) - only the
    text parts are drawn, so there is no double render."""
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
    assert _texts(interface) == ["let me read"]
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

    assert "Review test.py" in _texts(interface)
    assert "It's safe to run." in _texts(interface)
    # the recorded tool call replayed itself (result present)
    out = interface.get_all_output()
    assert "not_a_real_tool" in out
    assert "file contents" in out
