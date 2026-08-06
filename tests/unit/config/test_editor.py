"""Tests for the config write seam — set/get, reactive observers, coercion.

The write path is `SolveigConfig.set`/`get` (dotted walk) plus the
`@config.on_change` decorator for observers, with `parse_config_value` doing
coarse string → Python coercion for CLI-typed values. The old
`set_config_value`/`get_config_value`/`change_field`/`subscribe` are gone.
"""

import pytest

from solveig.config import SolveigConfig
from solveig.config.editor import parse_config_value

pytestmark = pytest.mark.anyio


def _cfg(**overrides) -> SolveigConfig:
    return SolveigConfig(cli_args=[], api={"url": "http://x"}, **overrides)


# ---------------------------------------------------------------------------
# get / set — the dotted traversals
# ---------------------------------------------------------------------------


class TestDottedGetSet:
    async def test_roundtrip_nested(self):
        c = _cfg()
        changed = await c.set("tools.http.timeout", 5.0)
        assert changed is True
        assert c.get("tools.http.timeout") == 5.0
        assert c.tools.http.timeout == 5.0

    async def test_top_level(self):
        c = _cfg()
        await c.set("disable_autonomy", True)
        assert c.get("disable_autonomy") is True
        assert c.disable_autonomy is True

    async def test_validate_assignment_coerces(self):
        c = _cfg()
        await c.set("api.type", "openai")
        assert c.api.type.name == "openai"


# ---------------------------------------------------------------------------
# parse_config_value — coarse string → Python coercion
# ---------------------------------------------------------------------------


class TestParseConfigValue:
    async def test_api_type_passthrough(self):
        c = _cfg()
        # APIType is not coarse-parsed; validate_assignment does the real work.
        value = parse_config_value(c, "api.type", "openai")
        await c.set("api.type", value)
        assert c.api.type.name == "openai"

    async def test_bool_false(self):
        c = _cfg()
        assert parse_config_value(c, "tools.command.enabled", "false") is False


# ---------------------------------------------------------------------------
# set — the single write seam (set + declared + notify)
# ---------------------------------------------------------------------------


class TestSet:
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

    async def test_notifies_observers_on_change(self):
        c = _cfg()
        seen: list[frozenset[str]] = []

        @c.on_change("api.max_context")
        async def probe(config, paths):
            seen.append(paths)

        await c.set("api.max_context", 999)
        assert seen == [frozenset({"api.max_context"})]

    async def test_notify_false_skips_observers(self):
        c = _cfg()
        seen: list[frozenset[str]] = []

        @c.on_change("api.max_context")
        async def probe(config, paths):
            seen.append(paths)

        await c.set("api.max_context", 999, notify=False)
        assert seen == []
        assert c.api.max_context == 999  # still visible, just not announced

    async def test_section_prefix_observer_matches_leaves(self):
        c = _cfg()
        seen: list[frozenset[str]] = []

        @c.on_change("api")
        async def probe(config, paths):
            seen.append(paths)

        await c.set("api.max_context", 999)
        # an observer on a prefix hears the leaf changes under it
        assert seen == [frozenset({"api.max_context"})]
