"""Integration tests for SessionManager."""

import json

import pytest

from solveig.schema.message import MessageHistory
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
    return MessageHistory(
        system_prompt="test",
        api_type=DEFAULT_CONFIG.api_type,
        encoder=DEFAULT_CONFIG.encoder,
    )


# ---------------------------------------------------------------------------
# _fuzzy_find
# ---------------------------------------------------------------------------


class TestFuzzyFind:
    async def test_direct_path_resolves_immediately(self, tmp_path):
        """If the name is a valid absolute path to an existing file, return it."""
        manager, _ = make_manager(tmp_path)
        real_file = tmp_path / "direct.json"
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
        real_file = tmp_path / "home_session.json"
        real_file.write_text('{"id": "home"}')

        manager, _ = make_manager(tmp_path)
        result = await manager._fuzzy_find("~/home_session.json")
        assert "home_session.json" in result
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

    async def test_store_content_is_valid_json(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        history = make_history()
        filename = await manager.store(history)
        path = tmp_path / "sessions" / filename
        data = json.loads(path.read_text())
        assert "id" in data
        assert "messages" in data
        assert "metadata" in data

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
        assert loaded["id"] == "namedtest"

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

    async def test_list_excludes_current_json(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        history = make_history()
        await manager.auto_save(history)  # creates .current.json
        sessions = await manager.list_sessions()
        assert all(".current" not in s.get("id", "") for s in sessions)

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


# ---------------------------------------------------------------------------
# auto_save
# ---------------------------------------------------------------------------


class TestAutoSave:
    async def test_auto_save_creates_current_json(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        history = make_history()
        await manager.auto_save(history)
        current = tmp_path / "sessions" / ".current.json"
        assert current.exists()

    async def test_auto_save_content_valid(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        history = make_history()
        await manager.auto_save(history)
        current = tmp_path / "sessions" / ".current.json"
        data = json.loads(current.read_text())
        assert data["id"] == "current"
        assert "messages" in data


# ---------------------------------------------------------------------------
# reconstruct_messages
# ---------------------------------------------------------------------------


class TestReconstructMessages:
    async def test_reconstruct_empty_messages(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        data = {"messages": []}
        result = manager.reconstruct_messages(data)
        assert result == []

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
        result = manager.reconstruct_messages(data)
        assert len(result) == 1
        assert isinstance(result[0], AssistantMessage)
        assert result[0].comment == "Hello!"

    async def test_reconstruct_user_comment(self, tmp_path):
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
        result = manager.reconstruct_messages(data)
        assert len(result) == 1
        assert isinstance(result[0], UserMessage)
        assert isinstance(result[0].responses[0], UserComment)
        assert result[0].responses[0].comment == "User said this"


# ---------------------------------------------------------------------------
# display_loaded_session
# ---------------------------------------------------------------------------


class TestDisplayLoadedSession:
    async def test_display_shows_session_header(self, tmp_path):
        manager, _ = make_manager(tmp_path)
        interface = MockInterface()
        history = make_history()
        session_data = {
            "id": "my-session",
            "model": "test-model",
            "metadata": {
                "message_count": 3,
                "total_tokens_sent": 100,
                "total_tokens_received": 50,
            },
            "messages": [],
        }
        await manager.display_loaded_session(session_data, history, interface)
        output = interface.get_all_output()
        assert "my-session" in output
        assert "test-model" in output
