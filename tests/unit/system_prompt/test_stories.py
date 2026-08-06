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

from solveig.system_prompt import compose
from solveig.system_prompt.compose import load_story, render_as_example

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

    @pytest.mark.no_file_mocking
    async def test_a_story_is_parsed_once(self, monkeypatch):
        """Stories are static once read - the prompt is recomposed every turn and
        was re-reading and re-validating the same JSONL each time."""
        calls = []
        original = compose.parse_conversation_blob
        monkeypatch.setattr(
            compose,
            "parse_conversation_blob",
            lambda text: calls.append(text) or original(text),
        )
        compose._clear_story_cache()
        await compose.load_story("sync_review")
        await compose.load_story("sync_review")
        assert len(calls) == 1


class TestDefaultSystemPrompt:
    """The default prompt must not describe a response format that no longer
    exists - it is sent on every turn, so a stale instruction is a live one."""

    @pytest.mark.parametrize(
        "phrase", ["Response format", "`comment`", "comment:", "tools:"]
    )
    def test_does_not_describe_the_retired_response_schema(self, phrase):
        from solveig.config import DEFAULT_SYSTEM_PROMPT

        assert phrase not in DEFAULT_SYSTEM_PROMPT

    def test_names_the_tasks_tool_as_it_is_actually_registered(self):
        """The prompt tells the model to call `tasks`; a rename would make that
        instruction point at nothing, and nothing else would fail."""
        from solveig.config import DEFAULT_SYSTEM_PROMPT
        from solveig.tools.available import CORE_TOOLS

        assert "tasks" in {tool.tool_name() for tool in CORE_TOOLS}
        assert "`tasks`" in DEFAULT_SYSTEM_PROMPT
