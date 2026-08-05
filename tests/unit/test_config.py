from unittest.mock import MagicMock

import anyconfig
import pytest

from solveig import bootstrap
from solveig.config import SolveigConfig
from tests.mocks import DEFAULT_CONFIG

# The full startup parse returns JUST the SolveigConfig (prompt/resume are
# fields on it); the old 3-tuple (config, prompt, resume) is gone.


async def test_defaults_and_nesting_dotted_flags():
    c = await bootstrap.parse_config_and_prompt(
        ["--api.url", "http://x", "hello world"]
    )
    assert c.api.url == "http://x"
    assert c.api.type.display_value() == "openai"  # inferred default
    assert c.tools.command.enabled is True
    assert c.tools.http.max_response_bytes == 50_000
    assert c.session.dir == ".solveig/sessions"
    assert c.prompt == "hello world"
    assert c.resume is None


async def test_cli_shortcuts_long_aliases():
    # cli_shortcuts give namespace-dropping LONG aliases (not -u short flags)
    c = await bootstrap.parse_config_and_prompt(
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
    assert (c.api.url, c.api.model, c.api.key.get_secret_value(), c.api.type.display_value()) == (
        "http://y",
        "gpt-4.1",
        "sk",
        "anthropic",
    )


async def test_no_verbose_no_with():
    c = await bootstrap.parse_config_and_prompt(["--url", "http://x"])
    assert not hasattr(c, "verbose")
    assert not hasattr(c, "with_")


@pytest.mark.no_file_mocking
async def test_file_and_cli_deep_merge(tmp_path):
    p = tmp_path / "c.json"
    anyconfig.dump({"api": {"url": "FILE", "model": "m"}}, str(p))
    c = await bootstrap.parse_config_and_prompt(
        ["--config", str(p), "--url", "CLI"]
    )
    assert c.api.url == "CLI"  # CLI overlays file
    assert c.api.model == "m"  # file value survives the overlay


async def test_model_dump_excludes_cli_and_runtime_fields():
    c = await bootstrap.parse_config_and_prompt(
        ["--url", "http://x", "--api-type", "anthropic"]
    )
    d = c.model_dump()
    assert d["api"]["type"] == "anthropic"
    assert isinstance(d["interface"]["theme"], str)
    # CLI-only + runtime fields never persist (exclude=True / PrivateAttr):
    for k in ("model_info", "config_files", "resume", "startup_mcp_servers"):
        assert k not in d


async def test_direct_construction_is_hermetic(tmp_path, monkeypatch):
    # With cli_args=[], SolveigConfig(...) must not read ambient files/CLI.
    monkeypatch.setattr(
        "solveig.config.sources.DEFAULT_CONFIG_SEARCH", [str(tmp_path / "nope")]
    )
    c = SolveigConfig(cli_args=[], api={"url": "http://direct"})
    assert c.api.url == "http://direct"
    assert c.prompt == "" and c.config_files == []


async def test_system_prompt_is_its_own_category():
    from solveig.config import DEFAULT_SYSTEM_PROMPT

    c = await bootstrap.parse_config_and_prompt(["--url", "http://x"])
    assert c.system_prompt.content == DEFAULT_SYSTEM_PROMPT
    assert c.system_prompt.add_examples is False
    assert c.system_prompt.add_os_info is False
    # add_examples/add_os_info moved OFF the top level onto system_prompt.*
    assert not hasattr(c, "add_examples")
    assert not hasattr(c, "add_os_info")


async def test_add_examples_shortcut_targets_nested_field():
    c = await bootstrap.parse_config_and_prompt(
        ["--url", "http://x", "--add-examples", "--add-os-info"]
    )
    assert c.system_prompt.add_examples is True
    assert c.system_prompt.add_os_info is True


async def test_command_disabled_the_same_uniform_way_as_any_tool():
    # command is NOT special: disabled via the generic tools.<name>.enabled path,
    # not a bespoke --no-commands flag.
    c = await bootstrap.parse_config_and_prompt(
        ["--url", "http://x", "--no-tools.command.enabled"]
    )
    assert c.tools.command.enabled is False
    assert c.tools.read.enabled is True  # others stay enabled


async def test_model_info_lives_on_client_not_config():
    # model_info is runtime API-reported provider state — never user config:
    # off the CLI, off model_dump, cached on the Client that reported it.
    from solveig.api.client import Client
    from solveig.api.types import ModelInfo

    c = await bootstrap.parse_config_and_prompt(["--url", "http://x"])
    assert not hasattr(c, "model_info")

    client = Client(DEFAULT_CONFIG, provider=MagicMock())
    assert client.model_info is None
    client.model_info = ModelInfo(model="gpt-4.1")
    assert client.model_info.model == "gpt-4.1"


async def test_default_plugin_paths_local_over_global():
    c = await bootstrap.parse_config_and_prompt(["--url", "http://x"])
    assert c.plugins.paths == ["./.solveig/plugins", "~/.solveig/plugins"]


@pytest.mark.no_file_mocking
async def test_declared_tracks_file_and_cli_fields(tmp_path):
    p = tmp_path / "c.json"
    anyconfig.dump({"api": {"model": "from-file"}}, str(p))
    c = await bootstrap.parse_config_and_prompt(
        ["--config", str(p), "--url", "CLI"]
    )
    # both the file-provided and CLI-provided leaf paths are declared for /config save
    assert "api.model" in c._declared_fields
    assert "api.url" in c._declared_fields
    # CLI-only fields never leak into _declared
    assert "prompt" not in c._declared_fields
    assert "startup_mcp_servers" not in c._declared_fields


async def test_declared_config_saves_only_declared_serialized():
    # /config save persists exactly the declared leaves, serialized: secret
    # un-masked, api type as its name, byte size as int, command patterns as
    # source strings — and nothing that wasn't explicitly set.
    c = await bootstrap.parse_config_and_prompt(
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
    c = await bootstrap.parse_config_and_prompt(
        ["--url", "http://x", "--model", "cli-model"]
    )
    assert c.api.key.get_secret_value() == "from-env"  # env supplies what CLI omitted
    assert c.api.model == "cli-model"  # CLI outranks env


async def test_mcp_url_flag_populates_servers():
    # The repeatable startup flag is --mcp-url (startup_mcp_servers); build()
    # turns it into the mcp dict keyed by URL.
    c = await bootstrap.parse_config_and_prompt(
        ["--url", "http://x", "--mcp-url", "stdio://a", "--mcp-url", "stdio://b"]
    )
    assert set(c.mcp) == {"stdio://a", "stdio://b"}
    assert c.mcp["stdio://a"].url == "stdio://a"


async def test_build_with_no_config_file_anywhere(tmp_path, monkeypatch):
    """A machine with no config file at all must still start.

    REGRESSION GUARD: `config_files` used to default to `DEFAULT_CONFIG_PATHS`
    (the search list, carrying an unexpanded `~`); a machine with nothing found
    kept the stale literal path and `/config save` / `_record_declared` tried to
    open `<cwd>/~/.solveig/config.yaml`. Nothing found must be [].
    """
    monkeypatch.chdir(tmp_path)  # guarantee ./.solveig/config.yaml is absent

    config = SolveigConfig.build([])

    # Nothing was found, so nothing should be recorded as a loaded file --
    # and crucially no unexpanded '~' path should survive into config_files.
    assert not any("~" in path for path in config.config_files)
    assert config._declared_fields == set()
