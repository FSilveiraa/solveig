from unittest.mock import MagicMock

import anyconfig
import pytest

from solveig import bootstrap
from solveig.api.types import APIType
from solveig.config import SolveigConfig

pytestmark = pytest.mark.anyio


async def test_defaults_and_nesting_dotted_flags():
    c, prompt, resume = await bootstrap.parse_config_and_prompt(
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
    c, _, _ = await bootstrap.parse_config_and_prompt(
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
    c, _, _ = await bootstrap.parse_config_and_prompt(["--url", "http://x"])
    assert not hasattr(c, "verbose")
    assert not hasattr(c, "with_")


@pytest.mark.no_file_mocking
async def test_file_and_cli_deep_merge(tmp_path):
    p = tmp_path / "c.json"
    anyconfig.dump({"api": {"url": "FILE", "model": "m"}}, str(p))
    c, _, _ = await bootstrap.parse_config_and_prompt(
        ["--config", str(p), "--url", "CLI"]
    )
    assert c.api.url == "CLI"  # CLI overlays file
    assert c.api.model == "m"  # file value survives the overlay


async def test_model_dump_excludes_cli_and_runtime_fields():
    c, _, _ = await bootstrap.parse_config_and_prompt(
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
    c = SolveigConfig(cli_args=[], api={"url": "http://direct"})
    assert c.api.url == "http://direct"
    assert c.prompt == "" and c.config_files is None


async def test_system_prompt_is_its_own_category():
    from solveig.system_prompt import DEFAULT_SYSTEM_PROMPT

    c, _, _ = await bootstrap.parse_config_and_prompt(["--url", "http://x"])
    assert c.system_prompt.content == DEFAULT_SYSTEM_PROMPT
    assert c.system_prompt.add_examples is False
    assert c.system_prompt.add_os_info is False
    # add_examples/add_os_info moved OFF the top level onto system_prompt.*
    assert not hasattr(c, "add_examples")
    assert not hasattr(c, "add_os_info")


async def test_add_examples_shortcut_targets_nested_field():
    c, _, _ = await bootstrap.parse_config_and_prompt(
        ["--url", "http://x", "--add-examples", "--add-os-info"]
    )
    assert c.system_prompt.add_examples is True
    assert c.system_prompt.add_os_info is True


async def test_command_disabled_the_same_uniform_way_as_any_tool():
    # command is NOT special: disabled via the generic tools.<name>.enabled path,
    # not a bespoke --no-commands flag.
    c, _, _ = await bootstrap.parse_config_and_prompt(
        ["--url", "http://x", "--no-tools.command.enabled"]
    )
    assert c.tools.command.enabled is False
    assert c.tools.read.enabled is True  # others stay enabled


async def test_model_info_lives_on_provider_ref_not_config():
    # model_info is runtime API-reported provider state — never user config:
    # off the CLI, off model_dump, cached on the ProviderRef that reported it.
    from solveig.api.client import Client
    from solveig.api.types import ModelInfo

    c, _, _ = await bootstrap.parse_config_and_prompt(["--url", "http://x"])
    assert not hasattr(c, "model_info")

    ref = Client(provider=MagicMock())
    assert ref.model_info is None
    ref.model_info = ModelInfo(model="gpt-4.1")
    assert ref.model_info.model == "gpt-4.1"


async def test_default_plugin_paths_local_over_global():
    c, _, _ = await bootstrap.parse_config_and_prompt(["--url", "http://x"])
    assert c.plugins.paths == ["./.solveig/plugins", "~/.solveig/plugins"]


@pytest.mark.no_file_mocking
async def test_declared_tracks_file_and_cli_fields(tmp_path):
    p = tmp_path / "c.json"
    anyconfig.dump({"api": {"model": "from-file"}}, str(p))
    c, _, _ = await bootstrap.parse_config_and_prompt(
        ["--config", str(p), "--url", "CLI"]
    )
    # both the file-provided and CLI-provided leaf paths are declared for /config save
    assert "api.model" in c._declared_fields
    assert "api.url" in c._declared_fields
    # CLI-only fields never leak into _declared
    assert "config" not in c._declared_fields
    assert "prompt" not in c._declared_fields


async def test_declared_config_saves_only_declared_serialized():
    # /config save persists exactly the declared leaves, serialized: secret
    # un-masked, api type as its name, byte size as int, command patterns as
    # source strings — and nothing that wasn't explicitly set.
    c, _, _ = await bootstrap.parse_config_and_prompt(
        [
            "--url",
            "http://x",
            "--key",
            "sk-secret",
            "--api-type",
            "anthropic",
            "--tools.command.auto_execute",
            "^ls",
            "--min_disk_space_left",
            "2GiB",
        ]
    )
    saved = c.declared_config()
    assert saved == {
        "api": {"url": "http://x", "key": "sk-secret", "type": "anthropic"},
        "tools": {"command": {"auto_execute": ["^ls"]}},
        "min_disk_space_left": 2 * 1024**3,
    }
    # a field left at its default is not written
    assert "session" not in saved
    assert "model" not in saved.get("api", {})


async def test_env_layer_between_cli_and_file(monkeypatch):
    monkeypatch.setenv("SOLVEIG_API__KEY", "from-env")
    monkeypatch.setenv("SOLVEIG_API__MODEL", "env-model")
    c, _, _ = await bootstrap.parse_config_and_prompt(
        ["--url", "http://x", "--model", "cli-model"]
    )
    assert c.api.key.get_secret_value() == "from-env"  # env supplies what CLI omitted
    assert c.api.model == "cli-model"  # CLI outranks env


async def test_mcp_flag_appends_into_servers():
    # NOTE: the repeatable startup flag is --mcp-server, not the historical bare
    # --mcp: under nested pydantic-settings the `mcp` submodel owns the bare
    # `--mcp` flag (whole-model JSON fallback), so a cli_shortcut can't reclaim it.
    c, _, _ = await bootstrap.parse_config_and_prompt(
        ["--url", "http://x", "--mcp-server", "stdio://a", "--mcp-server", "stdio://b"]
    )
    assert set(c.mcp.servers) == {"stdio://a", "stdio://b"}


async def test_build_with_no_config_file_anywhere(tmp_path, monkeypatch):
    """A machine with no config file at all must still start.

    REGRESSION (currently failing, bug not yet fixed): `config_files` defaults
    to `DEFAULT_CONFIG_PATHS`, which carries an unexpanded `~`.
    `ConfigFileSource` stamps the *resolved* list over that default, but when
    nothing is found it stamps `[]` — which is falsy, so pydantic keeps the raw
    default instead. `_record_declared()` then hands those literal paths to
    anyconfig, which tries to open `<cwd>/~/.solveig/config.yaml` and raises
    FileNotFoundError.

    Reproduces only outside the test fixtures' usual patching and only when no
    config file exists, which is why it survived: `conftest.default_config_file`
    empties the *search* list, not the field default.
    """
    monkeypatch.chdir(tmp_path)  # guarantee ./.solveig/config.yaml is absent

    config = SolveigConfig.build([])

    # Nothing was found, so nothing should be recorded as a loaded file --
    # and crucially no unexpanded '~' path should survive into config_files.
    assert not any("~" in path for path in config.config_files)
    assert config._declared_fields == set()
