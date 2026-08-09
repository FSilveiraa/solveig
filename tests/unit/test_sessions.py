"""Pin the session-file format contract: legacy blob + log format.

The reader (`parse_conversation_blob`) must handle both formats transparently
so old session files and story files keep loading alongside the append-only
JSONL a live session writes.
"""

import json

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_core import to_jsonable_python

from solveig.session.manager import SessionManager, parse_conversation_blob

pytestmark = pytest.mark.anyio


def _msg_lines(*messages: ModelRequest | ModelResponse) -> str:
    """Serialize messages to newline-terminated JSONL lines."""
    lines = ""
    for msg in messages:
        lines += json.dumps(to_jsonable_python([msg])[0], default=str) + "\n"
    return lines


def _meta_line(sent: int = 0, received: int = 0) -> str:
    return json.dumps({"session_meta": True, "total_tokens_sent": sent, "total_tokens_received": received}) + "\n"


# ---------------------------------------------------------------------------
# parse_conversation_blob
# ---------------------------------------------------------------------------


class TestLegacyBlob:
    @pytest.mark.no_file_mocking
    async def test_story_file_still_loads(self):
        """The real story file (single JSON object with messages key) keeps loading."""
        from anyio import Path

        from solveig.utils.file import Filesystem

        story_path = Path(__file__).parent.parent.parent / "solveig" / "system_prompt" / "stories" / "sync_review.jsonl"
        content = await Filesystem.read_file(story_path)
        parsed = parse_conversation_blob(content.content)
        assert len(parsed["messages"]) >= 1
        assert parsed["total_tokens_sent"] == 0  # stories have no totals

    async def test_legacy_blob_with_totals(self):
        """A legacy session blob with totals round-trips correctly."""

        msgs = [ModelRequest(parts=[UserPromptPart(content="hi")])]
        serialized = to_jsonable_python(msgs)
        blob = json.dumps({"messages": serialized, "total_tokens_sent": 100, "total_tokens_received": 50})
        parsed = parse_conversation_blob(blob)
        assert len(parsed["messages"]) == 1
        assert parsed["total_tokens_sent"] == 100
        assert parsed["total_tokens_received"] == 50

    async def test_legacy_blob_without_totals(self):
        """A legacy blob with no totals defaults to 0."""
        msgs = [ModelRequest(parts=[UserPromptPart(content="hi")])]
        blob = json.dumps({"messages": to_jsonable_python(msgs)})
        parsed = parse_conversation_blob(blob)
        assert parsed["total_tokens_sent"] == 0


class TestLogFormat:
    async def test_messages_only_no_meta(self):
        """Log format with no meta line (crashed session): zero totals, messages intact."""
        lines = _msg_lines(
            ModelRequest(parts=[UserPromptPart(content="one")]),
            ModelResponse(parts=[TextPart(content="two")]),
        )
        parsed = parse_conversation_blob(lines)
        assert len(parsed["messages"]) == 2
        assert parsed["total_tokens_sent"] == 0

    async def test_messages_and_meta(self):
        """Log format with trailing meta line: last meta wins."""
        lines = _msg_lines(
            ModelRequest(parts=[UserPromptPart(content="hi")]),
        ) + _meta_line(sent=42, received=58)
        parsed = parse_conversation_blob(lines)
        assert len(parsed["messages"]) == 1
        assert parsed["total_tokens_sent"] == 42
        assert parsed["total_tokens_received"] == 58

    async def test_last_meta_wins(self):
        """Multiple meta lines → only the last one counts."""
        lines = (
            _msg_lines(ModelRequest(parts=[UserPromptPart(content="a")]))
            + _meta_line(sent=10, received=5)
            + _msg_lines(ModelRequest(parts=[UserPromptPart(content="b")]))
            + _meta_line(sent=25, received=15)
        )
        parsed = parse_conversation_blob(lines)
        assert len(parsed["messages"]) == 2
        assert parsed["total_tokens_sent"] == 25
        assert parsed["total_tokens_received"] == 15

    async def test_empty_text(self):
        """Empty file → empty result, no crash."""
        parsed = parse_conversation_blob("")
        assert parsed["messages"] == []
        assert parsed["total_tokens_sent"] == 0

    async def test_whitespace_only(self):
        """Whitespace-only file → empty result."""
        parsed = parse_conversation_blob("   \n\n  \n")
        assert parsed["messages"] == []


class TestSerializationRoundtrip:
    async def test_serialize_then_parse(self):
        """Messages serialized via _serialize_messages roundtrip through the reader."""
        msgs = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[TextPart(content="hi there")]),
            ModelRequest(parts=[UserPromptPart(content="goodbye")]),
        ]
        lines = SessionManager._serialize_messages(msgs) + _meta_line(sent=99, received=44)
        parsed = parse_conversation_blob(lines)
        assert len(parsed["messages"]) == 3
        assert isinstance(parsed["messages"][0], ModelRequest)
        assert isinstance(parsed["messages"][1], ModelResponse)
        assert parsed["total_tokens_sent"] == 99

    async def test_partial_serialize_with_start(self):
        """_serialize_messages(messages, start=2) skips the first 2 messages."""
        msgs = [
            ModelRequest(parts=[UserPromptPart(content="a")]),
            ModelRequest(parts=[UserPromptPart(content="b")]),
            ModelRequest(parts=[UserPromptPart(content="c")]),
        ]
        lines = SessionManager._serialize_messages(msgs, start=2)
        parsed = parse_conversation_blob(lines)
        assert len(parsed["messages"]) == 1
        # The one message should be "c"
        assert parsed["messages"][0].parts[0].content == "c"
