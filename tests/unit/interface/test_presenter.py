import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    UserPromptPart,
)

from solveig.interface.presenter import present_message, present_part
from solveig.interface.render import Markdown, Reasoning, Style, Text

pytestmark = pytest.mark.anyio


def test_present_part_maps_conversational_parts():
    assert present_part(UserPromptPart(content="hi")) == Text("hi", Style.DEFAULT)
    assert present_part(TextPart(content="**bold**")) == Markdown("**bold**")
    assert present_part(ThinkingPart(content="hmm")) == Reasoning("hmm")


def test_present_part_skips_empty_and_non_conversational():
    assert present_part(TextPart(content="   ")) is None
    assert present_part(ThinkingPart(content="")) is None
    assert present_part(ToolCallPart(tool_name="read", args={})) is None
    # multimodal (non-str) user content is not a plain Text node here
    assert present_part(UserPromptPart(content=["x", "y"])) is None


def test_present_message_orders_and_drops_empties():
    resp = ModelResponse(
        parts=[
            ThinkingPart(content="planning"),
            TextPart(content=""),  # dropped
            TextPart(content="done"),
            ToolCallPart(tool_name="read", args={}),  # dropped (tool phase)
        ]
    )
    assert present_message(resp) == [Reasoning("planning"), Markdown("done")]

    req = ModelRequest(parts=[UserPromptPart(content="go")])
    assert present_message(req) == [Text("go", Style.DEFAULT)]
