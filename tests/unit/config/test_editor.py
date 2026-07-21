import pytest

from solveig.api import APIType
from solveig.config import SolveigConfig
from solveig.config.editor import (
    CONFIG_EDITABLE_FIELDS,
    apply_config_field,
    get_config_value,
    parse_config_value,
    set_config_value,
)


def _cfg() -> SolveigConfig:
    # Hermetic construction (no _PENDING_ARGV) — kwargs only, no CLI/file/env.
    return SolveigConfig(api={"url": "http://x"})


def test_dotted_get_set_roundtrip():
    c = _cfg()
    set_config_value(c, "tools.http.timeout", 5.0)
    assert get_config_value(c, "tools.http.timeout") == 5.0
    assert c.tools.http.timeout == 5.0


def test_top_level_path_has_no_dot():
    c = _cfg()
    set_config_value(c, "disable_autonomy", True)
    assert get_config_value(c, "disable_autonomy") is True
    assert c.disable_autonomy is True


def test_set_reparses_via_validate_assignment():
    # setattr on the leaf model fires ApiConfig's before-validator, coercing the
    # string to the real APIType — no bespoke coercion in the editor.
    c = _cfg()
    set_config_value(c, "api.type", "anthropic")
    assert c.api.type is APIType.ANTHROPIC


def test_parse_config_value_coarse_parses_then_set_reparses():
    c = _cfg()
    # parse_config_value only coarsely parses (string passthrough for APIType);
    # the set does the real coercion.
    value = parse_config_value(c, "api.type", "gemini")
    set_config_value(c, "api.type", value)
    assert c.api.type is APIType.GEMINI

    # bool leaf is parsed to a real bool (bool("false") pitfall handled)
    assert parse_config_value(c, "tools.command.enabled", "false") is False


def test_registry_uses_dotted_paths():
    assert "api.key" in CONFIG_EDITABLE_FIELDS
    assert "tools.command.enabled" in CONFIG_EDITABLE_FIELDS
    assert "tools.http.timeout" in CONFIG_EDITABLE_FIELDS
    # dropped flat/removed fields
    assert "no_commands" not in CONFIG_EDITABLE_FIELDS
    assert "model" not in CONFIG_EDITABLE_FIELDS
    assert "verbose" not in CONFIG_EDITABLE_FIELDS


@pytest.mark.anyio
async def test_apply_records_declared_for_save():
    # A runtime set is explicit user intent → recorded in _declared (what
    # /config save persists). tools.http.timeout has no post-set hook, so
    # provider_ref/interface are unused here.
    c = _cfg()
    await apply_config_field("tools.http.timeout", 3.0, c, None, None)
    assert "tools.http.timeout" in c._declared
    assert c.tools.http.timeout == 3.0
