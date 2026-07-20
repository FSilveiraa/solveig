import anyconfig
import pytest

from solveig.api import APIType
from solveig.config import SolveigConfig

pytestmark = pytest.mark.anyio


async def test_defaults_and_nesting_dotted_flags():
    c, prompt, resume = await SolveigConfig.parse_config_and_prompt(
        ["--api.url", "http://x", "hello world"]
    )
    assert c.api.url == "http://x"
    assert c.api.type is APIType.OPENAI  # inferred default
    assert c.tools.command.enabled is True
    assert c.tools.http.max_response_bytes == 50_000
    assert c.session.dir == ".solveig/sessions"
    assert prompt == "hello world"
    assert resume is None


async def test_cli_shortcuts_long_aliases():
    # cli_shortcuts give namespace-dropping LONG aliases (not -u short flags)
    c, _, _ = await SolveigConfig.parse_config_and_prompt(
        [
            "--url",
            "http://y",
            "--model",
            "gpt-4.1",
            "--key",
            "sk",
            "--api-type",
            "anthropic",
        ]
    )
    assert (c.api.url, c.api.model, c.api.key, c.api.type) == (
        "http://y",
        "gpt-4.1",
        "sk",
        APIType.ANTHROPIC,
    )


async def test_no_verbose_no_with():
    c, _, _ = await SolveigConfig.parse_config_and_prompt(["--url", "http://x"])
    assert not hasattr(c, "verbose")
    assert not hasattr(c, "with_")


@pytest.mark.no_file_mocking
async def test_file_and_cli_deep_merge(tmp_path):
    p = tmp_path / "c.json"
    anyconfig.dump({"api": {"url": "FILE", "model": "m"}}, str(p))
    c, _, _ = await SolveigConfig.parse_config_and_prompt(
        ["--config", str(p), "--url", "CLI"]
    )
    assert c.api.url == "CLI"  # CLI overlays file
    assert c.api.model == "m"  # file value survives the overlay


async def test_model_dump_excludes_cli_and_runtime_fields():
    c, _, _ = await SolveigConfig.parse_config_and_prompt(
        ["--url", "http://x", "--api-type", "anthropic"]
    )
    d = c.to_dict()
    assert d["api"]["type"] == "anthropic"
    assert isinstance(d["interface"]["theme"], str)
    # CLI-only + runtime fields never persist:
    for k in ("model_info", "prompt", "config", "resume", "add_mcp"):
        assert k not in d


async def test_direct_construction_is_hermetic(tmp_path, monkeypatch):
    # With no _PENDING_ARGV, SolveigConfig(...) must not read ambient files/CLI.
    monkeypatch.setattr(
        "solveig.config.sources.DEFAULT_CONFIG_SEARCH", [str(tmp_path / "nope")]
    )
    c = SolveigConfig(api={"url": "http://direct"})
    assert c.api.url == "http://direct"
    assert c.prompt == "" and c.config is None


async def test_mcp_flag_appends_into_servers():
    # NOTE: the repeatable startup flag is --mcp-server, not the historical bare
    # --mcp: under nested pydantic-settings the `mcp` submodel owns the bare
    # `--mcp` flag (whole-model JSON fallback), so a cli_shortcut can't reclaim it.
    c, _, _ = await SolveigConfig.parse_config_and_prompt(
        ["--url", "http://x", "--mcp-server", "stdio://a", "--mcp-server", "stdio://b"]
    )
    assert set(c.mcp.servers) == {"stdio://a", "stdio://b"}
