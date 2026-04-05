"""Integration tests for SessionManager."""

import json

import pytest

from solveig.schema.message import SystemMessage
from solveig.schema.message.message_history import MessageHistory
from solveig.sessions.manager import SessionManager
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_manager(tmp_path):
    cfg = DEFAULT_CONFIG.with_(sessions_dir=str(tmp_path / "sessions"))
    return SessionManager(config=cfg), cfg


def make_history():
    return MessageHistory(system_prompt="test", config=DEFAULT_CONFIG)


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
        history = make_history()
        await manager.store(history, "mysession")

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
        history = make_history()
        filename = await manager.store(history)
        sessions_dir = tmp_path / "sessions"
        assert (sessions_dir / filename).exists()

    async def test_store_with_name_includes_name_in_filename(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        history = make_history()
        filename = await manager.store(history, "mytest")
        assert "mytest" in filename

    async def test_store_content_is_valid_jsonl(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        history = make_history()
        filename = await manager.store(history)
        path = tmp_path / "sessions" / filename
        lines = [line for line in path.read_text().splitlines() if line.strip()]
        assert all(json.loads(line) for line in lines)

    async def test_load_latest_after_store(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        history = make_history()
        await manager.store(history, "latest_test")
        loaded = await manager.load()
        assert "id" in loaded

    async def test_load_by_name(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        history = make_history()
        await manager.store(history, "namedtest")
        loaded = await manager.load("namedtest")
        assert "namedtest" in loaded["id"]

    async def test_load_no_sessions_raises(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        with pytest.raises(FileNotFoundError):
            await manager.load()

    async def test_load_unknown_name_raises(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        history = make_history()
        await manager.store(history, "existing")
        with pytest.raises(FileNotFoundError):
            await manager.load("nonexistent")

    async def test_load_returns_stored_session(self, tmp_path):
        """When no named sessions exist, load() returns the auto-saved session."""
        manager, _ = make_manager(tmp_path)
        history = make_history()
        await manager.store(history)
        loaded = await manager.load()
        expected_id = manager.current_path.name.removesuffix(".jsonl")
        assert loaded["id"] == expected_id


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
        history = make_history()
        await manager.store(history, "alpha")
        await manager.store(history, "beta")
        sessions = await manager.list_sessions()
        assert len(sessions) == 2

    async def test_list_includes_stored_session(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        history = make_history()
        await manager.store(history)
        sessions = await manager.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == manager.current_path.name.removesuffix(".jsonl")

    async def test_delete_removes_file(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        history = make_history()
        filename = await manager.store(history, "todelete")
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
        history = make_history()
        await manager.store(history, "good")

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
        history = make_history()
        await manager.store(history)
        assert manager.current_path is not None
        assert (tmp_path / "sessions" / manager.current_path.name).exists()

    async def test_store_reuses_same_file(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        history = make_history()
        await manager.store(history)
        path_after_first = manager.current_path
        await manager.store(history)
        assert manager.current_path == path_after_first

    async def test_store_content_valid(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        history = make_history()
        await manager.store(history)
        lines = [
            line
            for line in (await manager.current_path.read_text()).splitlines()
            if line.strip()
        ]
        assert all(json.loads(line) for line in lines)


# ---------------------------------------------------------------------------
# reconstruct_messages
# ---------------------------------------------------------------------------


class TestReconstructMessages:
    async def test_reconstruct_empty_messages(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        data = {"messages": []}
        message_history = MessageHistory("")
        message_history.load_from_session(data)
        assert len(message_history.messages) == 1
        assert isinstance(message_history.messages[0], SystemMessage)

    async def test_reconstruct_assistant_message(self, tmp_path):
        from solveig.schema.message.assistant import AssistantMessage

        manager, _ = make_manager(tmp_path)
        data = {
            "messages": [
                {
                    "role": "assistant",
                    "content": json.dumps({"comment": "Hello!", "tools": None}),
                }
            ]
        }
        message_history = MessageHistory(system_prompt="")
        message_history.load_from_session(data)
        messages = message_history.messages
        assert len(messages) == 2  # system + user
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], AssistantMessage)
        assert messages[1].comment == "Hello!"

    async def test_reconstruct_user_comment(self, tmp_path):
        from solveig.schema.message.message_history import MessageHistory
        from solveig.schema.message.user import UserComment, UserMessage

        manager, _ = make_manager(tmp_path)
        data = {
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(
                        {"responses": [{"comment": "User said this"}]}
                    ),
                }
            ]
        }
        message_history = MessageHistory(system_prompt="")
        message_history.load_from_session(data)
        messages = message_history.messages
        assert len(messages) == 2  # system + user
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], UserMessage)
        assert isinstance(messages[1].responses[0], UserComment)
        assert messages[1].responses[0].comment == "User said this"


# ---------------------------------------------------------------------------
# display_loaded_session
# ---------------------------------------------------------------------------


class TestDisplayLoadedSession:
    async def test_display_shows_session_header(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        interface = MockInterface()
        history = make_history()
        session_data = {"id": "my-session", "messages": []}
        await manager.display_loaded_session(session_data, history, interface)
        output = interface.get_all_output()
        assert "my-session" in output
