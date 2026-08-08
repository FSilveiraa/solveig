"""Integration tests for SubcommandRegistry dispatch and handlers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from solveig.api.client import Client
from solveig.config import SolveigConfig
from solveig.config.editor import config_list  # noqa: F401 — triggers @subcommand
from solveig.session.conversation import Conversation
from solveig.mcp_servers.client import mcp_list  # noqa: F401 — triggers @subcommand
from solveig.session.manager import SessionManager, session_list  # noqa: F401
from solveig.subcommands.registry import SubcommandRegistry
from solveig.user_message_queue import UserMessageQueue
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENTINEL = object()


def _default_session_manager():
    mgr = MagicMock()
    mgr.list_sessions = AsyncMock(return_value=[])
    mgr.store = AsyncMock(return_value="session.json")
    mgr.load = AsyncMock(return_value={"id": "t", "messages": [], "usage": MagicMock()})
    mgr.delete = AsyncMock(return_value="session.json")
    mgr.announce_resumed_session = AsyncMock()
    return mgr


def make_registry(config=None, session_manager=_SENTINEL):
    if session_manager is _SENTINEL:
        session_manager = _default_session_manager()
    cfg = (
        config
        if config is not None
        else SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump())
    )
    conversation = Conversation()
    provider_ref = Client(cfg, provider=MagicMock())
    interface = MockInterface()
    user_message_queue = UserMessageQueue()
    registry = SubcommandRegistry(
        config=cfg,
        conversation=conversation,
        interface=interface,
        client=provider_ref,
        session_manager=session_manager,
        user_message_queue=user_message_queue,
    )
    return registry, conversation, cfg


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    """Test the __call__ dispatch mechanism."""

    async def test_unknown_command_returns_false(self):
        registry, _, _ = make_registry()
        result = await registry("/unknown")
        assert result is False

    async def test_empty_input_returns_false(self):
        registry, _, _ = make_registry()
        result = await registry("")
        assert result is False

    async def test_known_command_returns_true(self):
        registry, _, _ = make_registry()
        result = await registry("/help")
        assert result is True

    async def test_two_token_key_matches_before_one_token(self):
        """'/config list' should dispatch to the 2-token handler, not '/config'."""
        registry, _, _ = make_registry()
        result = await registry("/config list")
        assert result is True
        # Should have shown the config block (title "Config (editable fields)")
        assert any("Config" in o for o in registry._interface.outputs)

    async def test_shlex_quoted_args_parsed(self):
        """Quoted tokens with spaces should be passed as a single argument."""
        registry, _, _ = make_registry()
        result = await registry('/config get "api.temperature"')
        assert result is True

    async def test_session_alias_dispatches(self):
        """/sessions (plural) is a registered alias for /session list."""
        registry, _, _ = make_registry()
        result = await registry("/sessions")
        assert result is True

    async def test_sessions_sub_alias_dispatches(self):
        """/sessions list dispatches via the /sessions alias with remaining tokens."""
        registry, _, _ = make_registry()
        result = await registry("/sessions list")
        assert result is True


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------


class TestHelpCommand:
    async def test_help_shows_basic_section(self):
        registry, _, _ = make_registry()
        await registry("/help")
        output = registry._interface.get_all_output()
        assert "Basic" in output

    async def test_help_shows_config_section(self):
        registry, _, _ = make_registry()
        await registry("/help")
        output = registry._interface.get_all_output()
        assert "Config" in output

    async def test_help_shows_tool_section(self):
        registry, _, _ = make_registry()
        await registry("/help")
        output = registry._interface.get_all_output()
        assert "Tools" in output

    async def test_help_mentions_exit(self):
        registry, _, _ = make_registry()
        await registry("/help")
        output = registry._interface.get_all_output()
        assert "/exit" in output


# ---------------------------------------------------------------------------
# /exit
# ---------------------------------------------------------------------------


class TestExitCommand:
    async def test_exit_calls_interface_stop(self):
        registry, _, _ = make_registry()
        await registry("/exit")
        assert "INTERFACE_STOPPED" in registry._interface.outputs


# ---------------------------------------------------------------------------
# /config commands
# ---------------------------------------------------------------------------


class TestConfigCommands:
    async def test_config_list_shows_all_fields(self):
        registry, _, _ = make_registry()
        await registry("/config list")
        output = registry._interface.get_all_output()
        assert "api.temperature" in output
        assert "api.model" in output

    async def test_config_shorthand_shows_all_fields(self):
        """/config alone behaves like /config list."""
        registry, _, _ = make_registry()
        await registry("/config")
        output = registry._interface.get_all_output()
        assert "api.temperature" in output

    async def test_config_get_known_field(self):
        registry, _, _ = make_registry()
        await registry("/config get api.temperature")
        output = registry._interface.get_all_output()
        assert "api.temperature" in output
        assert "0.0" in output  # DEFAULT_CONFIG.api.temperature == 0.0

    async def test_config_get_no_args_shows_error(self):
        registry, _, _ = make_registry()
        await registry("/config get")
        assert any("ERROR" in o for o in registry._interface.outputs)

    async def test_config_get_unknown_field_shows_error(self):
        registry, _, _ = make_registry()
        await registry("/config get nonexistent_field")
        assert any("ERROR" in o for o in registry._interface.outputs)

    async def test_config_set_known_field_with_value(self):
        registry, _, cfg = make_registry()
        await registry("/config set api.temperature 0.7")
        assert cfg.api.temperature == pytest.approx(0.7)

    async def test_config_set_key_equals_value_form(self):
        """/config set temperature=0.3 — key=value syntax."""
        registry, _, cfg = make_registry()
        await registry("/config set api.temperature=0.3")
        assert cfg.api.temperature == pytest.approx(0.3)

    async def test_config_set_unknown_field_shows_error(self):
        registry, _, _ = make_registry()
        await registry("/config set nonexistent_field value")
        assert any("ERROR" in o for o in registry._interface.outputs)

    async def test_config_set_no_args_shows_error(self):
        registry, _, _ = make_registry()
        await registry("/config set")
        assert any("ERROR" in o for o in registry._interface.outputs)

    async def test_config_set_stream_bool(self):
        registry, _, cfg = make_registry()
        await registry("/config set stream true")
        assert cfg.stream is True

    async def test_config_get_api_key_masked(self):
        registry, _, _ = make_registry()
        await registry("/config get api.key")
        # api.key is masked — value shown as *** not the actual key
        output = registry._interface.get_all_output()
        assert "test-key" not in output
        assert "***" in output


# ---------------------------------------------------------------------------
# /model commands
# ---------------------------------------------------------------------------


class TestModelCommands:
    async def test_model_info_shows_model_name(self):
        registry, _, _ = make_registry()
        await registry("/model info")
        output = registry._interface.get_all_output()
        # No model info loaded yet — ProviderRef.model_info starts as None
        assert "No model info loaded" in output

    async def test_model_info_no_model_shows_no_info(self):
        cfg = SolveigConfig(
            cli_args=[],
            api=DEFAULT_CONFIG.api.model_dump() | {"model": None},
        )
        registry, _, _ = make_registry(config=cfg)
        await registry("/model info")
        output = registry._interface.get_all_output()
        assert "No model info loaded" in output

    async def test_model_set_updates_config(self):
        registry, _, cfg = make_registry()
        await registry("/model set new-model-name")
        assert cfg.api.model == "new-model-name"


# NOTE: there is no "no session_manager" class here any more. It passed
# `session_manager=None` — a value the registry's own constructor signature
# forbids — and asserted the bare `AttributeError` that surfaced deep inside a
# handler. That failure mode is gone: an unfillable parameter is refused as a
# declaration error, pinned by
# `test_a_subcommand_asking_for_an_uninjectable_type_is_refused`
# in tests/unit/test_subcommand_base.py.


# ---------------------------------------------------------------------------
# /session commands (with mocked session_manager)
# ---------------------------------------------------------------------------


class TestSessionCommandsWithManager:
    def _make_mock_manager(self):
        manager = MagicMock()
        manager.list_sessions = AsyncMock(return_value=[])
        manager.store = AsyncMock(return_value="2024-01-01_mysession.json")
        manager.load = AsyncMock(
            return_value={"id": "test", "messages": [], "usage": MagicMock()}
        )
        manager.delete = AsyncMock(return_value="test.json")
        manager.announce_resumed_session = AsyncMock()
        return manager

    async def test_session_list_empty(self):
        manager = self._make_mock_manager()
        registry, _, _ = make_registry(session_manager=manager)
        await registry("/session list")
        # Empty → "No saved sessions" message
        assert any(
            "No saved sessions" in o or "No stored sessions" in o
            for o in registry._interface.outputs
        )

    async def test_session_list_with_sessions(self):
        manager = self._make_mock_manager()
        manager.list_sessions = AsyncMock(
            return_value=[
                {
                    "id": "my-session",
                    "message_count": 5,
                    "total_tokens_sent": 100,
                    "total_tokens_received": 50,
                }
            ]
        )
        registry, _, _ = make_registry(session_manager=manager)
        await registry("/session list")
        output = registry._interface.get_all_output()
        assert "my-session" in output

    async def test_session_store_calls_manager(self):
        manager = self._make_mock_manager()
        registry, _, _ = make_registry(session_manager=manager)
        await registry("/store mysession")
        manager.store.assert_called_once()
        assert any("Session stored as" in o for o in registry._interface.outputs)

    async def test_session_store_no_name(self):
        manager = self._make_mock_manager()
        registry, _, _ = make_registry(session_manager=manager)
        await registry("/store")
        manager.store.assert_called_once()

    async def test_session_delete_confirms_yes(self):
        manager = self._make_mock_manager()
        registry, _, _ = make_registry(session_manager=manager)
        registry._interface.choices = [0]  # 0 = "Yes"
        await registry("/session delete test")
        manager.delete.assert_called_once_with("test")
        assert any("Deleted session" in o for o in registry._interface.outputs)

    async def test_session_delete_not_found_shows_error(self):
        manager = self._make_mock_manager()
        manager.delete = AsyncMock(
            side_effect=FileNotFoundError("No session matching 'ghost'")
        )
        registry, _, _ = make_registry(session_manager=manager)
        await registry("/session delete ghost")
        assert any("ERROR" in o for o in registry._interface.outputs)

    async def test_session_resume_loads_session(self):
        manager = self._make_mock_manager()
        registry, _, _ = make_registry(session_manager=manager)
        await registry("/resume")
        manager.load.assert_called_once()
        assert any("Session resumed." in o for o in registry._interface.outputs)

    async def test_session_resume_not_found_shows_error(self):
        manager = self._make_mock_manager()
        manager.load = AsyncMock(side_effect=FileNotFoundError("No sessions found"))
        registry, _, _ = make_registry(session_manager=manager)
        await registry("/resume")
        assert any("ERROR" in o for o in registry._interface.outputs)


# ---------------------------------------------------------------------------
# Tool subcommands
# ---------------------------------------------------------------------------


class TestToolSubcommands:
    async def test_tool_subcommands_registered(self):
        """At least some tool subcommands should be present in the registry's store."""
        from solveig.subcommands.base import SUBCOMMANDS

        registry, _, _ = make_registry()
        assert len(SUBCOMMANDS.all()) > 0

    async def test_command_tool_subcommand_registered(self):
        from solveig.subcommands.base import SUBCOMMANDS

        registry, _, _ = make_registry()
        names = [name for s in SUBCOMMANDS.all() for name in s.subcommands]
        assert "/command" in names or "/cmd" in names
