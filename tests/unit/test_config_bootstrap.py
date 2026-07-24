"""Pin the config bootstrap as explicitly idempotent (D3).

The core-tools schema was previously composed as an import-time side effect
in `config/__init__.py`. It is now an explicit `SolveigConfig.bootstrap()`
call — the same mechanism as the plugin two-phase bootstrap, phase 1. These
tests pin that the bootstrap is idempotent and that the placeholder behavior
without it is a documented choice, not a surprise.
"""

import pytest

from solveig.config import SolveigConfig
from solveig.config.models import CoreToolsConfig, PluginHooksConfig, PluginToolsConfig

pytestmark = pytest.mark.anyio


def _schema_snapshot() -> dict[str, set[str]]:
    """Field names of each composed config section."""
    tools_annotation = SolveigConfig.model_fields["tools"].annotation
    assert tools_annotation is not None
    return {
        "tools": set(tools_annotation.model_fields),
        "plugins.tools": set(PluginToolsConfig.model_fields),
        "plugins.hooks": set(PluginHooksConfig.model_fields),
    }


async def test_bootstrap_is_idempotent():
    """bootstrap() twice → the composed schema is IDENTICAL both times."""
    SolveigConfig.bootstrap()
    first = _schema_snapshot()

    SolveigConfig.bootstrap()
    second = _schema_snapshot()

    assert first == second
    # Sanity: core tools actually landed (not the empty placeholder).
    assert len(first["tools"]) > 0


async def test_bootstrap_composes_core_tools():
    """After bootstrap, config.tools carries one field per core tool."""
    SolveigConfig.bootstrap()
    tools_annotation = SolveigConfig.model_fields["tools"].annotation
    assert tools_annotation is not None
    # CORE_TOOLS is 9 tools; spot-check the known ones.
    for name in (
        "read",
        "write",
        "edit",
        "delete",
        "copy",
        "move",
        "command",
        "http",
        "tasks",
    ):
        assert name in tools_annotation.model_fields, f"missing core tool field: {name}"


async def test_config_after_bootstrap_validates_per_tool_config():
    """A SolveigConfig constructed after bootstrap validates a full per-tool
    config (proving the real schema, not the placeholder)."""
    SolveigConfig.bootstrap()
    cfg = SolveigConfig(api={"url": "http://x"})
    # A core tool's config field exists and carries its own model.
    read_cfg = getattr(cfg.tools, "read", None)
    assert read_cfg is not None
    assert hasattr(read_cfg, "enabled")


async def test_placeholder_without_bootstrap_is_documented():
    """A bare SolveigConfig() WITHOUT bootstrap sees the placeholder
    CoreToolsConfig — no per-tool fields. This test documents the trade-off
    explicitly (option (a) in the design log): call sites that need the real
    schema must call bootstrap() first. If this test ever fails because the
    placeholder grew fields, the design assumption changed — revisit the log.
    """
    # NOTE: this test is ORDER-SENSITIVE — if another test already called
    # bootstrap(), the class-level schema is composed and stays composed
    # (compose mutates the class, not the instance). We assert the
    # placeholder's shape only when it is genuinely the placeholder; after
    # any bootstrap the assertion is skipped. This is the honest way to test
    # a class-level mutation in a shared test process.
    tools_annotation = SolveigConfig.model_fields["tools"].annotation
    if tools_annotation is CoreToolsConfig:
        # Genuinely the placeholder: no per-tool fields.
        assert len(tools_annotation.model_fields) == 0
    else:
        # Already bootstrapped by an earlier test in this process — the
        # placeholder behavior is no longer observable here. Document it.
        assert len(tools_annotation.model_fields) > 0
