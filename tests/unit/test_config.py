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
    assert (c.api.url, c.api.model, c.api.key.get_secret_value(), c.api.type) == (
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


async def test_system_prompt_is_its_own_category():
    from solveig.config.models import DEFAULT_SYSTEM_PROMPT

    c, _, _ = await SolveigConfig.parse_config_and_prompt(["--url", "http://x"])
    assert c.system_prompt.content == DEFAULT_SYSTEM_PROMPT
    assert c.system_prompt.add_examples is False
    assert c.system_prompt.add_os_info is False
    # add_examples/add_os_info moved OFF the top level onto system_prompt.*
    assert not hasattr(c, "add_examples")
    assert not hasattr(c, "add_os_info")


async def test_add_examples_shortcut_targets_nested_field():
    c, _, _ = await SolveigConfig.parse_config_and_prompt(
        ["--url", "http://x", "--add-examples", "--add-os-info"]
    )
    assert c.system_prompt.add_examples is True
    assert c.system_prompt.add_os_info is True


async def test_command_disabled_the_same_uniform_way_as_any_tool():
    # command is NOT special: disabled via the generic tools.<name>.enabled path,
    # not a bespoke --no-commands flag.
    c, _, _ = await SolveigConfig.parse_config_and_prompt(
        ["--url", "http://x", "--no-tools.command.enabled"]
    )
    assert c.tools.command.enabled is False
    assert c.tools.read.enabled is True  # others stay enabled


async def test_model_info_is_not_a_cli_flag():
    # model_info is runtime API-reported state, not user config — off the CLI
    # entirely, settable at runtime via the property.
    c, _, _ = await SolveigConfig.parse_config_and_prompt(["--url", "http://x"])
    assert c.model_info is None
    from solveig.api import ModelInfo

    c.model_info = ModelInfo(model="gpt-4.1")
    assert c.model_info.model == "gpt-4.1"
    assert "model_info" not in c.to_dict()


async def test_default_plugin_paths_local_over_global():
    c, _, _ = await SolveigConfig.parse_config_and_prompt(["--url", "http://x"])
    assert c.plugins.paths == ["./.solveig/plugins", "~/.solveig/plugins"]


@pytest.mark.no_file_mocking
async def test_declared_tracks_file_and_cli_fields(tmp_path):
    p = tmp_path / "c.json"
    anyconfig.dump({"api": {"model": "from-file"}}, str(p))
    c, _, _ = await SolveigConfig.parse_config_and_prompt(
        ["--config", str(p), "--url", "CLI"]
    )
    # both the file-provided and CLI-provided leaf paths are declared for /config save
    assert "api.model" in c._declared
    assert "api.url" in c._declared
    # CLI-only fields never leak into _declared
    assert "config" not in c._declared
    assert "prompt" not in c._declared


async def test_env_layer_between_cli_and_file(monkeypatch):
    monkeypatch.setenv("SOLVEIG_API__KEY", "from-env")
    monkeypatch.setenv("SOLVEIG_API__MODEL", "env-model")
    c, _, _ = await SolveigConfig.parse_config_and_prompt(
        ["--url", "http://x", "--model", "cli-model"]
    )
    assert c.api.key.get_secret_value() == "from-env"  # env supplies what CLI omitted
    assert c.api.model == "cli-model"  # CLI outranks env


async def test_mcp_flag_appends_into_servers():
    # NOTE: the repeatable startup flag is --mcp-server, not the historical bare
    # --mcp: under nested pydantic-settings the `mcp` submodel owns the bare
    # `--mcp` flag (whole-model JSON fallback), so a cli_shortcut can't reclaim it.
    c, _, _ = await SolveigConfig.parse_config_and_prompt(
        ["--url", "http://x", "--mcp-server", "stdio://a", "--mcp-server", "stdio://b"]
    )
    assert set(c.mcp.servers) == {"stdio://a", "stdio://b"}
