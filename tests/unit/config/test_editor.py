"""Tests for config traversals — set_config_value, get_config_value, change_field."""

import pytest

from solveig.api import APIType
from solveig.config import SolveigConfig, set_config_value
from solveig.config.editor import parse_config_value

pytestmark = pytest.mark.anyio


def _cfg() -> SolveigConfig:
    return SolveigConfig(cli_args=[], api={"url": "http://x"})


# ---------------------------------------------------------------------------
# set_config_value / get_config_value — the low-level dotted traversals
# ---------------------------------------------------------------------------


class TestDottedGetSet:
    async def test_roundtrip_nested(self):
        c = _cfg()
        set_config_value(c, "tools.http.timeout", 5.0)
        assert c.get("tools.http.timeout") == 5.0
        assert c.tools.http.timeout == 5.0

    async def test_top_level(self):
        c = _cfg()
        set_config_value(c, "disable_autonomy", True)
        assert c.get("disable_autonomy") is True
        assert c.disable_autonomy is True

    async def test_validate_assignment_coerces(self):
        c = _cfg()
        set_config_value(c, "api.type", "anthropic")
        assert c.api.type is APIType.ANTHROPIC


# ---------------------------------------------------------------------------
# parse_config_value — coarse string → Python coercion
# ---------------------------------------------------------------------------


class TestParseConfigValue:
    async def test_string_passthrough(self):
        c = _cfg()
        # APIType is not coarse-parsed; validate_assignment does the real work
        value = parse_config_value(c, "api.type", "gemini")
        set_config_value(c, "api.type", value)
        assert c.api.type is APIType.GEMINI

    async def test_bool_false(self):
        c = _cfg()
        assert parse_config_value(c, "tools.command.enabled", "false") is False


# ---------------------------------------------------------------------------
# change_field — the user-edit write seam (set + declared + notify)
# ---------------------------------------------------------------------------


class TestChangeField:
    async def test_sets_and_records_declared(self):
        c = _cfg()
        changed = await c.set("tools.http.timeout", 3.0)
        assert changed is True
        assert "tools.http.timeout" in c._declared_fields
        assert c.tools.http.timeout == 3.0

    async def test_same_value_is_noop(self):
        c = _cfg()
        await c.set("api.max_context", 12345)
        changed = await c.set("api.max_context", 12345)
        assert changed is False

    async def test_notifies_observers(self):
        c = _cfg()
        seen = []

        class Probe:
            async def config_changed(self, config, paths):
                seen.append(paths)

        c.subscribe(Probe())
        await c.set("api.max_context", 999)
        assert seen == [frozenset({"api.max_context"})]
