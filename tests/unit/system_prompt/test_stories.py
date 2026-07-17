"""Unit tests for solveig/system_prompt/__init__.py's story loading and
rendering - render_as_example() is tested against a small fixed fixture
list[ModelMessage], not the real sync_review.jsonl content, so future edits
to that story don't break this test."""

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)

from solveig.system_prompt import load_story, render_as_example

pytestmark = pytest.mark.anyio


class TestRenderAsExample:
    def test_renders_user_and_assistant_text(self):
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[TextPart(content="hi there")]),
        ]

        result = render_as_example(messages)

        assert result == "user: hello\nassistant: hi there"

    def test_renders_tool_calls_mechanically(self):
        messages = [
            ModelRequest(parts=[UserPromptPart(content="read it")]),
            ModelResponse(
                parts=[
                    TextPart(content="On it"),
                    ToolCallPart("read", {"path": "~/Sync/hello.py"}),
                ]
            ),
        ]

        result = render_as_example(messages)

        assert result == (
            "user: read it\nassistant: On it\n  [calls read(path='~/Sync/hello.py')]"
        )

    def test_multiple_consecutive_assistant_turns(self):
        """No new user prompt between two ModelResponses - both render as
        separate assistant: lines with no user: line between them, matching
        the real agentic loop where several responses can follow one prompt."""
        messages = [
            ModelRequest(parts=[UserPromptPart(content="go")]),
            ModelResponse(parts=[TextPart(content="step one")]),
            ModelResponse(parts=[TextPart(content="step two")]),
        ]

        result = render_as_example(messages)

        assert result == "user: go\nassistant: step one\nassistant: step two"


class TestLoadStory:
    @pytest.mark.no_file_mocking
    async def test_loads_sync_review_story(self):
        messages = await load_story("sync_review")
        assert len(messages) > 0

    async def test_unknown_story_raises(self):
        with pytest.raises(FileNotFoundError):
            await load_story("does-not-exist")
