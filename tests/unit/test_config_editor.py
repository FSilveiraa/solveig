"""Tests for editor utilities — unwrap, parse, editable_fields."""

import typing

import pytest

from solveig.config.editor import _parse_field_value, _unwrap_optional, editable_fields
from tests.mocks import DEFAULT_CONFIG

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# _unwrap_optional
# ---------------------------------------------------------------------------


class TestUnwrapOptional:
    async def test_str_or_none_unwraps_to_str(self):
        tp = typing.Optional[str]  # noqa: UP045
        assert _unwrap_optional(tp) is str

    async def test_plain_str_unchanged(self):
        assert _unwrap_optional(str) is str

    async def test_union_non_optional_unchanged(self):
        tp = typing.Union[str, int]  # noqa: UP007
        assert _unwrap_optional(tp) is tp


# ---------------------------------------------------------------------------
# _parse_field_value
# ---------------------------------------------------------------------------


class TestParseFieldValue:
    async def test_bool_false_variants(self):
        for raw in ("false", "False", "FALSE", "no", "0", "off"):
            assert _parse_field_value(bool, raw) is False

    async def test_float(self):
        assert _parse_field_value(float, "0.75") == pytest.approx(0.75)

    async def test_list_multiple_items(self):
        result = _parse_field_value(list, "a,b, c")
        assert result == ["a", "b", "c"]

    async def test_str_plain(self):
        assert _parse_field_value(str, "gpt-4o") == "gpt-4o"


# ---------------------------------------------------------------------------
# editable_fields — the schema-derived registry
# ---------------------------------------------------------------------------


class TestEditableFields:
    async def test_core_leaves_present(self):
        fields = editable_fields(DEFAULT_CONFIG)
        for path in (
            "api.model",
            "api.url",
            "api.temperature",
            "api.max_context",
            "interface.theme",
            "interface.code_theme",
            "tools.command.enabled",
            "tools.http.timeout",
            "session.auto_save",
            "briefing",
            "disable_autonomy",
        ):
            assert path in fields, f"Missing: {path}"

    async def test_excluded_fields_absent(self):
        fields = editable_fields(DEFAULT_CONFIG)
        for path in ("prompt", "resume", "startup_mcp_servers", "cli_args"):
            assert path not in fields, f"Should be excluded: {path}"

    async def test_plugin_sections_appear_after_parse(self):
        """Composed plugin sections are editable after a full bootstrap parse."""
        from solveig.config import SolveigConfig

        config, _, _ = await SolveigConfig.parse_config_and_prompt([])
        fields = editable_fields(config)
        assert "plugins.tools.tree.enabled" in fields
        assert "plugins.hooks.shellcheck.enabled" in fields
