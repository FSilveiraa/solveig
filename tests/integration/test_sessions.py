from solveig.config import SolveigConfig
"""Integration tests for SessionManager.

`SessionManager.store()`/`load()` (de)serialize a `Conversation`
(`messages: list[ModelMessage]` + `usage: RunUsage`) via pydantic-ai's own
`ModelMessagesTypeAdapter`/`to_jsonable_python`, one JSON blob per session
file - not the removed `MessageHistory`. Message reconstruction from a stored
blob is pydantic-ai's own job now (`ModelMessagesTypeAdapter.validate_python`),
so there's nothing Solveig-specific left to unit test there; `load()`'s
round-trip is exercised via `store()` + `load()` below instead of by hand-
building request/response dicts.

Resume is reactive: `Conversation.load()` repopulates the messages and the
transcript replays each (see `tests/unit/interface/test_transcript.py`).
`announce_resumed_session()` only shows the banner - this file covers that plus
store/load round-tripping.
"""

import json

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    UserPromptPart,
)
from pydantic_ai.usage import RunUsage

from solveig.session.conversation import Conversation
from solveig.session.manager import SessionManager
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_manager(tmp_path):
    cfg = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump(), session={"dir": str(tmp_path / "sessions")})
    return SessionManager(config=cfg), cfg


# ---------------------------------------------------------------------------
# parse_conversation_blob
# ---------------------------------------------------------------------------


class TestParseConversationBlob:
    def test_parses_messages_and_token_counts(self):
        from pydantic_ai.messages import ModelRequest, UserPromptPart
        from pydantic_core import to_jsonable_python

        from solveig.session.manager import parse_conversation_blob

        messages = [ModelRequest(parts=[UserPromptPart(content="hi")])]
        blob_text = json.dumps(
            {
                "total_tokens_sent": 10,
                "total_tokens_received": 5,
                "messages": to_jsonable_python(messages),
            }
        )

        result = parse_conversation_blob(blob_text)

        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], ModelRequest)
        assert result["messages"][0].parts[0].content == "hi"
        assert result["total_tokens_sent"] == 10
        assert result["total_tokens_received"] == 5

    def test_defaults_missing_token_counts_to_zero(self):
        from pydantic_core import to_jsonable_python

        from solveig.session.manager import parse_conversation_blob

        blob_text = json.dumps({"messages": to_jsonable_python([])})

        result = parse_conversation_blob(blob_text)

        assert result["messages"] == []
        assert result["total_tokens_sent"] == 0
        assert result["total_tokens_received"] == 0


# ---------------------------------------------------------------------------
# _fuzzy_find
# ---------------------------------------------------------------------------


class TestFuzzyFind:
    async def test_direct_path_resolves_immediately(self, tmp_path):
        """If the name is a valid absolute path to an existing file, return it."""
        manager, _ = make_manager(tmp_path)
        real_file = tmp_path / "direct.jsonl"
        real_file.write_text('{"id": "direct"}')

        result = await manager._fuzzy_find(str(real_file))
        assert result == str(real_file)

    async def test_fuzzy_match_by_name_fragment(self, tmp_path):
        """Session stored under a name can be fuzzy-found by a fragment."""
        manager, _ = make_manager(tmp_path)
        await manager.store(Conversation(), "mysession")

        result = await manager._fuzzy_find("mysession")
        assert "mysession" in result

    async def test_fuzzy_find_not_found_raises(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        with pytest.raises(FileNotFoundError, match="ghost"):
            await manager._fuzzy_find("ghost")

    async def test_tilde_path_resolves(self, tmp_path, monkeypatch):
        """A ~ path that exists is resolved correctly."""
        monkeypatch.setenv("HOME", str(tmp_path))
        real_file = tmp_path / "home_session.jsonl"
        real_file.write_text('{"id": "home"}')

        manager, _ = make_manager(tmp_path)
        result = await manager._fuzzy_find("~/home_session.jsonl")
        assert "home_session.jsonl" in result
        assert "~" not in result


# ---------------------------------------------------------------------------
# store / load
# ---------------------------------------------------------------------------


class TestStoreLoad:
    async def test_store_creates_file(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        filename = await manager.store(Conversation())
        sessions_dir = tmp_path / "sessions"
        assert (sessions_dir / filename).exists()

    async def test_store_with_name_includes_name_in_filename(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        filename = await manager.store(Conversation(), "mytest")
        assert "mytest" in filename

    async def test_store_content_is_valid_jsonl(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        filename = await manager.store(Conversation())
        path = tmp_path / "sessions" / filename
        lines = [line for line in path.read_text().splitlines() if line.strip()]
        assert all(json.loads(line) for line in lines)

    async def test_load_latest_after_store(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        await manager.store(Conversation(), "latest_test")
        loaded = await manager.load()
        assert "id" in loaded

    async def test_load_by_name(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        await manager.store(Conversation(), "namedtest")
        loaded = await manager.load("namedtest")
        assert "namedtest" in loaded["id"]

    async def test_load_no_sessions_raises(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        with pytest.raises(FileNotFoundError):
            await manager.load()

    async def test_load_unknown_name_raises(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        await manager.store(Conversation(), "existing")
        with pytest.raises(FileNotFoundError):
            await manager.load("nonexistent")

    async def test_load_returns_stored_session(self, tmp_path):
        """When no named sessions exist, load() returns the auto-saved session."""
        manager, _ = make_manager(tmp_path)
        await manager.store(Conversation())
        loaded = await manager.load()
        expected_id = manager.current_path.name.removesuffix(".jsonl")
        assert loaded["id"] == expected_id

    async def test_store_then_load_round_trips_messages_and_usage(self, tmp_path):
        """The pydantic-ai ModelMessagesTypeAdapter round-trip: messages and
        token totals survive a store -> load cycle unchanged."""
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        manager, _ = make_manager(tmp_path)
        conversation = Conversation()
        await conversation.append(ModelRequest(parts=[UserPromptPart(content="hello")]))
        conversation.usage.input_tokens = 42
        conversation.usage.output_tokens = 7

        await manager.store(conversation, "roundtrip")
        loaded = await manager.load("roundtrip")

        assert len(loaded["messages"]) == 1
        assert isinstance(loaded["messages"][0], ModelRequest)
        assert loaded["messages"][0].parts[0].content == "hello"
        assert loaded["usage"].input_tokens == 42
        assert loaded["usage"].output_tokens == 7


# ---------------------------------------------------------------------------
# list_sessions / delete
# ---------------------------------------------------------------------------


class TestListDelete:
    async def test_list_returns_empty_when_no_sessions(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        sessions = await manager.list_sessions()
        assert sessions == []

    async def test_list_returns_stored_sessions(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        await manager.store(Conversation(), "alpha")
        await manager.store(Conversation(), "beta")
        sessions = await manager.list_sessions()
        assert len(sessions) == 2

    async def test_list_includes_stored_session(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        await manager.store(Conversation())
        sessions = await manager.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == manager.current_path.name.removesuffix(".jsonl")

    async def test_delete_removes_file(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        filename = await manager.store(Conversation(), "todelete")
        sessions_dir = tmp_path / "sessions"
        assert (sessions_dir / filename).exists()
        await manager.delete("todelete")
        assert not (sessions_dir / filename).exists()

    async def test_delete_nonexistent_raises(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        with pytest.raises(FileNotFoundError):
            await manager.delete("nonexistent")

    async def test_list_sessions_skips_corrupted_file(self, tmp_path):
        """list_sessions() silently skips files with invalid JSON content."""
        manager, _ = make_manager(tmp_path)
        await manager.store(Conversation(), "good")

        sessions_dir = tmp_path / "sessions"
        (sessions_dir / "broken.jsonl").write_text("not valid json {{{{")

        sessions = await manager.list_sessions()
        assert len(sessions) == 1
        assert "good" in sessions[0]["id"]


# ---------------------------------------------------------------------------
# auto_save
# ---------------------------------------------------------------------------


class TestStore:
    async def test_store_creates_timestamped_file(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        await manager.store(Conversation())
        assert manager.current_path is not None
        assert (tmp_path / "sessions" / manager.current_path.name).exists()

    async def test_store_reuses_same_file(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        await manager.store(Conversation())
        path_after_first = manager.current_path
        await manager.store(Conversation())
        assert manager.current_path == path_after_first

    async def test_store_content_valid(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        await manager.store(Conversation())
        lines = [
            line
            for line in (await manager.current_path.read_text()).splitlines()
            if line.strip()
        ]
        assert all(json.loads(line) for line in lines)


class TestCheckpoint:
    async def test_checkpoint_creates_new_file_without_touching_current_path(
        self, tmp_path
    ):
        manager, _ = make_manager(tmp_path)
        await manager.store(Conversation())
        live_path = manager.current_path
        checkpoint_name = await manager.checkpoint(Conversation())
        assert manager.current_path == live_path
        assert checkpoint_name != live_path.name
        assert (tmp_path / "sessions" / checkpoint_name).exists()

    async def test_checkpoint_survives_later_store(self, tmp_path):
        """Branch-button regression: the checkpoint must keep the pre-truncation
        state after the live session auto-saves past the branch point."""
        manager, _ = make_manager(tmp_path)
        full = Conversation()
        await full.append(ModelRequest(parts=[UserPromptPart(content="before-branch")]))
        await manager.store(Conversation())
        checkpoint_name = await manager.checkpoint(full)
        await manager.store(Conversation())  # auto-save past the branch point
        loaded = await manager.load(checkpoint_name.removesuffix(".jsonl"))
        assert len(loaded["messages"]) == 1
        assert loaded["messages"][0].parts[0].content == "before-branch"


# ---------------------------------------------------------------------------
# announce_resumed_session
# ---------------------------------------------------------------------------


class TestAnnounceResumedSession:
    async def test_announce_shows_message_and_token_counts(self, tmp_path):
        """The banner comes from the loaded session_data; the messages
        themselves render reactively through the transcript (see
        tests/unit/interface/test_transcript.py for the replay rendering)."""
        manager, _ = make_manager(tmp_path)
        interface = MockInterface()
        session_data = {
            "messages": [ModelRequest(parts=[UserPromptPart(content="hi")])],
            "usage": RunUsage(input_tokens=12, output_tokens=34),
        }

        await manager.announce_resumed_session(session_data, interface)

        output = interface.get_all_output()
        assert "1" in output  # message count
        assert "12" in output
        assert "34" in output
