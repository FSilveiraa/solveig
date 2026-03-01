"""Integration tests for SubcommandRunner dispatch and handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from solveig.llm import ClientRef
from solveig.schema.message import MessageHistory
from solveig.subcommand.runner import SubcommandRunner
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_runner(config=None, session_manager=None):
    cfg = config if config is not None else DEFAULT_CONFIG.with_()
    history = MessageHistory(
        system_prompt="test", api_type=cfg.api_type, encoder=cfg.encoder
    )
    client_ref = ClientRef(client=MagicMock())
    runner = SubcommandRunner(
        config=cfg,
        message_history=history,
        client_ref=client_ref,
        session_manager=session_manager,
    )
    return runner, history, cfg


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    """Test the __call__ dispatch mechanism."""

    async def test_unknown_command_returns_false(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        result = await runner("/unknown", interface)
        assert result is False

    async def test_empty_input_returns_false(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        result = await runner("", interface)
        assert result is False

    async def test_known_command_returns_true(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        result = await runner("/help", interface)
        assert result is True

    async def test_two_token_key_matches_before_one_token(self):
        """'/config list' should dispatch to _config_list_cmd, not _config_list_cmd via '/config'."""
        runner, _, _ = make_runner()
        interface = MockInterface()
        result = await runner("/config list", interface)
        assert result is True
        # Should have shown the config block (title "Config (editable fields)")
        assert any("Config" in o for o in interface.outputs)

    async def test_shlex_quoted_args_parsed(self):
        """Quoted tokens with spaces should be passed as a single argument."""
        runner, _, _ = make_runner()
        interface = MockInterface()
        # /config get with quoted field name — field name won't have spaces but
        # this exercises shlex parsing: '"temperature"' → 'temperature'
        result = await runner('/config get "temperature"', interface)
        assert result is True

    async def test_session_alias_dispatches(self):
        """/sessions (plural) is a registered alias for /session."""
        runner, _, _ = make_runner()
        interface = MockInterface()
        result = await runner("/sessions", interface)
        assert result is True

    async def test_sessions_sub_alias_dispatches(self):
        """/sessions list dispatches to the same handler as /session list."""
        runner, _, _ = make_runner()
        interface = MockInterface()
        result = await runner("/sessions list", interface)
        assert result is True


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------


class TestHelpCommand:
    async def test_help_shows_basic_section(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        await runner("/help", interface)
        output = interface.get_all_output()
        assert "Basic sub-commands" in output

    async def test_help_shows_config_section(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        await runner("/help", interface)
        output = interface.get_all_output()
        assert "Config sub-commands" in output

    async def test_help_shows_tool_section(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        await runner("/help", interface)
        output = interface.get_all_output()
        assert "Tool sub-commands" in output

    async def test_help_mentions_exit(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        await runner("/help", interface)
        output = interface.get_all_output()
        assert "/exit" in output


# ---------------------------------------------------------------------------
# /exit
# ---------------------------------------------------------------------------


class TestExitCommand:
    async def test_exit_calls_interface_stop(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        await runner("/exit", interface)
        assert "INTERFACE_STOPPED" in interface.outputs


# ---------------------------------------------------------------------------
# /config commands
# ---------------------------------------------------------------------------


class TestConfigCommands:
    async def test_config_list_shows_all_fields(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        await runner("/config list", interface)
        output = interface.get_all_output()
        assert "temperature" in output
        assert "verbose" in output
        assert "model" in output

    async def test_config_shorthand_shows_all_fields(self):
        """/config alone behaves like /config list."""
        runner, _, _ = make_runner()
        interface = MockInterface()
        await runner("/config", interface)
        output = interface.get_all_output()
        assert "temperature" in output

    async def test_config_get_known_field(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        await runner("/config get temperature", interface)
        output = interface.get_all_output()
        assert "temperature" in output
        assert "0.0" in output  # DEFAULT_CONFIG.temperature == 0.0

    async def test_config_get_no_args_shows_error(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        await runner("/config get", interface)
        assert any("Error" in o for o in interface.outputs)

    async def test_config_get_unknown_field_shows_error(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        await runner("/config get nonexistent_field", interface)
        assert any("Error" in o for o in interface.outputs)

    async def test_config_set_known_field_with_value(self):
        runner, _, cfg = make_runner()
        interface = MockInterface()
        await runner("/config set temperature 0.7", interface)
        assert cfg.temperature == pytest.approx(0.7)
        assert any("✅" in o for o in interface.outputs)

    async def test_config_set_key_equals_value_form(self):
        """/config set temperature=0.3 — key=value syntax."""
        runner, _, cfg = make_runner()
        interface = MockInterface()
        await runner("/config set temperature=0.3", interface)
        assert cfg.temperature == pytest.approx(0.3)

    async def test_config_set_unknown_field_shows_error(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        await runner("/config set nonexistent_field value", interface)
        assert any("Error" in o for o in interface.outputs)

    async def test_config_set_no_args_shows_error(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        await runner("/config set", interface)
        assert any("Error" in o for o in interface.outputs)

    async def test_config_set_verbose_bool(self):
        runner, _, cfg = make_runner()
        interface = MockInterface()
        await runner("/config set verbose true", interface)
        assert cfg.verbose is True

    async def test_config_get_api_key_masked(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        await runner("/config get api_key", interface)
        # api_key is masked — value shown as *** not the actual key
        output = interface.get_all_output()
        assert "test-key" not in output
        assert "***" in output


# ---------------------------------------------------------------------------
# /model commands
# ---------------------------------------------------------------------------


class TestModelCommands:
    async def test_model_info_shows_model_name(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        await runner("/model", interface)
        output = interface.get_all_output()
        assert "test-model" in output

    async def test_model_info_no_model_shows_warning(self):
        cfg = DEFAULT_CONFIG.with_(model=None)
        runner, _, _ = make_runner(config=cfg)
        interface = MockInterface()
        await runner("/model", interface)
        assert any("Warning" in o or "No model" in o for o in interface.outputs)

    async def test_model_set_updates_config(self):
        runner, _, cfg = make_runner()
        interface = MockInterface()
        with patch(
            "solveig.subcommand.runner.fetch_and_apply_model_info",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await runner("/model set new-model-name", interface)
        assert cfg.model == "new-model-name"

    async def test_model_info_alias(self):
        runner, _, _ = make_runner()
        interface = MockInterface()
        await runner("/model info", interface)
        output = interface.get_all_output()
        assert "test-model" in output


# ---------------------------------------------------------------------------
# /session commands (no session_manager)
# ---------------------------------------------------------------------------


class TestSessionCommandsNoManager:
    async def test_session_list_no_manager_shows_error(self):
        runner, _, _ = make_runner(session_manager=None)
        interface = MockInterface()
        await runner("/session", interface)
        assert any("Error" in o for o in interface.outputs)

    async def test_session_store_no_manager_shows_error(self):
        runner, _, _ = make_runner(session_manager=None)
        interface = MockInterface()
        await runner("/store", interface)
        assert any("Error" in o for o in interface.outputs)

    async def test_session_resume_no_manager_shows_error(self):
        runner, _, _ = make_runner(session_manager=None)
        interface = MockInterface()
        await runner("/resume", interface)
        assert any("Error" in o for o in interface.outputs)

    async def test_session_delete_no_manager_shows_error(self):
        runner, _, _ = make_runner(session_manager=None)
        interface = MockInterface()
        await runner("/session delete myname", interface)
        assert any("Error" in o for o in interface.outputs)


# ---------------------------------------------------------------------------
# /session commands (with mocked session_manager)
# ---------------------------------------------------------------------------


class TestSessionCommandsWithManager:
    def _make_mock_manager(self):
        manager = MagicMock()
        manager.list_sessions = AsyncMock(return_value=[])
        manager.store = AsyncMock(return_value="2024-01-01_mysession.json")
        manager.load = AsyncMock(
            return_value={"id": "test", "metadata": {}, "messages": []}
        )
        manager.delete = AsyncMock(return_value="test.json")
        manager._fuzzy_find = AsyncMock(return_value="/some/path/test.json")
        manager.reconstruct_messages = MagicMock(return_value=[])
        manager.display_loaded_session = AsyncMock()
        return manager

    async def test_session_list_empty(self):
        manager = self._make_mock_manager()
        runner, _, _ = make_runner(session_manager=manager)
        interface = MockInterface()
        await runner("/session list", interface)
        assert any("No stored sessions" in o for o in interface.outputs)

    async def test_session_list_with_sessions(self):
        manager = self._make_mock_manager()
        manager.list_sessions = AsyncMock(
            return_value=[
                {
                    "id": "my-session",
                    "_mtime": 1700000000,
                    "metadata": {"message_count": 5},
                }
            ]
        )
        runner, _, _ = make_runner(session_manager=manager)
        interface = MockInterface()
        await runner("/session list", interface)
        output = interface.get_all_output()
        assert "my-session" in output

    async def test_session_store_calls_manager(self):
        manager = self._make_mock_manager()
        runner, _, _ = make_runner(session_manager=manager)
        interface = MockInterface()
        await runner("/store mysession", interface)
        manager.store.assert_called_once()
        assert any("✅" in o for o in interface.outputs)

    async def test_session_store_no_name(self):
        manager = self._make_mock_manager()
        runner, _, _ = make_runner(session_manager=manager)
        interface = MockInterface()
        await runner("/store", interface)
        manager.store.assert_called_once()
        # name=None passed
        args, _ = manager.store.call_args
        assert args[1] is None  # second arg is name

    async def test_session_delete_confirms_yes(self):
        manager = self._make_mock_manager()
        runner, _, _ = make_runner(session_manager=manager)
        interface = MockInterface(choices=[0])  # 0 = "Yes"
        await runner("/session delete test", interface)
        manager.delete.assert_called_once_with("test")
        assert any("✅" in o for o in interface.outputs)

    async def test_session_delete_confirms_no(self):
        manager = self._make_mock_manager()
        runner, _, _ = make_runner(session_manager=manager)
        interface = MockInterface(choices=[1])  # 1 = "No"
        await runner("/session delete test", interface)
        manager.delete.assert_not_called()

    async def test_session_delete_no_args_shows_error(self):
        manager = self._make_mock_manager()
        runner, _, _ = make_runner(session_manager=manager)
        interface = MockInterface()
        await runner("/session delete", interface)
        assert any("Error" in o for o in interface.outputs)

    async def test_session_delete_not_found_shows_error(self):
        manager = self._make_mock_manager()
        manager._fuzzy_find = AsyncMock(
            side_effect=FileNotFoundError("No session matching 'ghost'")
        )
        runner, _, _ = make_runner(session_manager=manager)
        interface = MockInterface()
        await runner("/session delete ghost", interface)
        assert any("Error" in o for o in interface.outputs)

    async def test_session_resume_loads_session(self):
        manager = self._make_mock_manager()
        runner, _, _ = make_runner(session_manager=manager)
        interface = MockInterface()
        await runner("/resume", interface)
        manager.load.assert_called_once()
        assert any("✅" in o for o in interface.outputs)

    async def test_session_resume_not_found_shows_error(self):
        manager = self._make_mock_manager()
        manager.load = AsyncMock(side_effect=FileNotFoundError("No sessions found"))
        runner, _, _ = make_runner(session_manager=manager)
        interface = MockInterface()
        await runner("/resume", interface)
        assert any("Error" in o for o in interface.outputs)


# ---------------------------------------------------------------------------
# Tool subcommands
# ---------------------------------------------------------------------------


class TestToolSubcommands:
    async def test_tool_subcommands_registered(self):
        """At least some tool subcommands should be present in the registry."""
        runner, _, _ = make_runner()
        # Core tools like /command, /read, /write etc. should be registered
        assert len(runner._tools) > 0

    async def test_command_tool_subcommand_registered(self):
        runner, _, _ = make_runner()
        assert "/command" in runner._registry or "/cmd" in runner._registry
