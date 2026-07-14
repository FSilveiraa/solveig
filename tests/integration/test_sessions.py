"""Integration tests for SessionManager.

`SessionManager.store()`/`load()` (de)serialize a `Conversation`
(`messages: list[ModelMessage]` + `usage: RunUsage`) via pydantic-ai's own
`ModelMessagesTypeAdapter`/`to_jsonable_python`, one JSON blob per session
file - not the removed `MessageHistory`. Message reconstruction from a stored
blob is pydantic-ai's own job now (`ModelMessagesTypeAdapter.validate_python`),
so there's nothing Solveig-specific left to unit test there; `load()`'s
round-trip is exercised via `store()` + `load()` below instead of by hand-
building request/response dicts.

`display_loaded_session(conversation, interface)` announces a resumed session
and replays each tool call - see `tests/plugins/test_shellcheck.py`/
`tests/unit/test_toolset.py` for the tool-call replay/orchestration paths;
this file only covers the session-level announcement.
"""

import json

import pytest

from solveig.conversation import Conversation
from solveig.sessions.manager import SessionManager
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_manager(tmp_path):
    cfg = DEFAULT_CONFIG.with_(sessions_dir=str(tmp_path / "sessions"))
    return SessionManager(config=cfg), cfg


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
        conversation = Conversation(
            messages=[ModelRequest(parts=[UserPromptPart(content="hello")])]
        )
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


# ---------------------------------------------------------------------------
# display_loaded_session
# ---------------------------------------------------------------------------


class TestDisplayLoadedSession:
    async def test_display_shows_message_and_token_counts(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        interface = MockInterface()
        conversation = Conversation()
        conversation.usage.input_tokens = 12
        conversation.usage.output_tokens = 34

        await manager.display_loaded_session(conversation, interface)

        output = interface.get_all_output()
        assert "12" in output
        assert "34" in output
