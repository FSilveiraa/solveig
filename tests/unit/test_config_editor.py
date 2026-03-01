"""Unit tests for solveig.config.editor."""

import typing
from unittest.mock import AsyncMock, MagicMock

import pytest

from solveig.config.editor import (
    CONFIG_EDITABLE_FIELDS,
    _parse_field_value,
    _unwrap_optional,
    apply_config_field,
)
from solveig.llm import ClientRef
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# _unwrap_optional
# ---------------------------------------------------------------------------


class TestUnwrapOptional:
    async def test_str_or_none_unwraps_to_str(self):
        tp = typing.Optional[str]  # noqa: UP045
        assert _unwrap_optional(tp) is str

    async def test_int_or_none_unwraps_to_int(self):
        tp = typing.Optional[int]  # noqa: UP045
        assert _unwrap_optional(tp) is int

    async def test_plain_str_unchanged(self):
        assert _unwrap_optional(str) is str

    async def test_plain_int_unchanged(self):
        assert _unwrap_optional(int) is int

    async def test_list_str_unchanged(self):
        tp = list[str]
        assert _unwrap_optional(tp) is tp

    async def test_union_non_optional_unchanged(self):
        tp = typing.Union[str, int]  # noqa: UP007
        # Not Optional (has two non-None members) — returned as-is
        result = _unwrap_optional(tp)
        assert result is tp


# ---------------------------------------------------------------------------
# _parse_field_value
# ---------------------------------------------------------------------------


class TestParseFieldValue:
    async def test_bool_true_variants(self):
        for raw in ("true", "True", "TRUE", "yes", "1", "on"):
            assert _parse_field_value("verbose", bool, raw) is True

    async def test_bool_false_variants(self):
        for raw in ("false", "False", "FALSE", "no", "0", "off"):
            assert _parse_field_value("verbose", bool, raw) is False

    async def test_int_plain(self):
        assert _parse_field_value("max_context", int, "1024") == 1024

    async def test_int_min_disk_space(self):
        result = _parse_field_value("min_disk_space_left", int, "1GiB")
        assert result == 1024**3

    async def test_float(self):
        assert _parse_field_value("temperature", float, "0.75") == pytest.approx(0.75)

    async def test_list_single_item(self):
        result = _parse_field_value("briefing", list, "BRIEFING.md")
        assert result == ["BRIEFING.md"]

    async def test_list_multiple_items(self):
        result = _parse_field_value("auto_allowed_paths", list, "a,b, c")
        assert result == ["a", "b", "c"]

    async def test_list_empty_string_returns_empty(self):
        result = _parse_field_value("briefing", list, "")
        assert result == []

    async def test_str_plain(self):
        assert _parse_field_value("model", str, "gpt-4o") == "gpt-4o"

    async def test_str_or_none_empty_returns_none(self):
        # model is str | None — empty string should become None
        result = _parse_field_value("model", type(None), "")
        assert result is None

    async def test_str_or_none_nonempty_returns_value(self):
        result = _parse_field_value("model", type(None), "claude-sonnet")
        assert result == "claude-sonnet"


# ---------------------------------------------------------------------------
# CONFIG_EDITABLE_FIELDS registry
# ---------------------------------------------------------------------------


class TestConfigEditableFields:
    async def test_expected_fields_present(self):
        expected = {
            "model",
            "temperature",
            "verbose",
            "max_context",
            "api_key",
            "url",
            "api_type",
            "briefing",
            "no_commands",
            "theme",
            "code_theme",
        }
        for field in expected:
            assert field in CONFIG_EDITABLE_FIELDS, f"Missing field: {field}"

    async def test_all_descriptions_non_empty(self):
        for field, desc in CONFIG_EDITABLE_FIELDS.items():
            assert desc, f"Empty description for field: {field}"

    async def test_all_fields_exist_on_config(self):
        for field in CONFIG_EDITABLE_FIELDS:
            assert hasattr(DEFAULT_CONFIG, field), f"Config missing field: {field}"


# ---------------------------------------------------------------------------
# apply_config_field
# ---------------------------------------------------------------------------


class TestApplyConfigField:
    async def test_sets_field_value(self):
        cfg = DEFAULT_CONFIG.with_(temperature=0.0)
        interface = MockInterface()
        client_ref = ClientRef(client=MagicMock())
        await apply_config_field("temperature", 0.9, cfg, client_ref, interface)
        assert cfg.temperature == pytest.approx(0.9)

    async def test_sets_verbose(self):
        cfg = DEFAULT_CONFIG.with_(verbose=False)
        interface = MockInterface()
        client_ref = ClientRef(client=MagicMock())
        await apply_config_field("verbose", True, cfg, client_ref, interface)
        assert cfg.verbose is True

    async def test_hook_called_for_encoder(self):
        """Changing encoder should update message_history.encoder via hook."""
        from solveig.schema.message import MessageHistory

        cfg = DEFAULT_CONFIG.with_(encoder="cl100k_base")
        history = MessageHistory(
            system_prompt="test", api_type=cfg.api_type, encoder=cfg.encoder
        )
        interface = MockInterface()
        client_ref = ClientRef(client=MagicMock())
        await apply_config_field("encoder", "gpt2", cfg, client_ref, interface, history)
        assert cfg.encoder == "gpt2"
        assert history.encoder == "gpt2"

    async def test_hook_called_for_max_context(self):
        """Changing max_context should update message_history.max_context via hook."""
        from solveig.schema.message import MessageHistory

        cfg = DEFAULT_CONFIG.with_(max_context=4096)
        history = MessageHistory(
            system_prompt="test",
            api_type=cfg.api_type,
            encoder=cfg.encoder,
            max_context=4096,
        )
        interface = MockInterface()
        client_ref = ClientRef(client=MagicMock())
        await apply_config_field(
            "max_context", 8192, cfg, client_ref, interface, history
        )
        assert cfg.max_context == 8192
        assert history.max_context == 8192

    async def test_model_hook_triggered(self):
        """Changing model calls fetch_and_apply_model_info via hook."""
        from unittest.mock import patch

        cfg = DEFAULT_CONFIG.with_(model="old-model")
        interface = MockInterface()
        client_ref = ClientRef(client=MagicMock())
        with patch(
            "solveig.config.editor.fetch_and_apply_model_info",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_fetch:
            await apply_config_field("model", "new-model", cfg, client_ref, interface)
        assert cfg.model == "new-model"
        mock_fetch.assert_called_once()
