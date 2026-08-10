import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.anyio

from solveig import bootstrap
from solveig.config import SolveigConfig
from solveig.config.models import (
    ApiConfig,
    MCPServerConfig,
    SystemPromptConfig,
    TuiConfig,
)
from solveig.interface import themes
from solveig.tools.base import ToolConfig
from solveig.tools.core.command import CommandConfig
from solveig.tools.core.http import HttpConfig


@pytest.fixture(autouse=True)
def _compose_for_models():
    """The core-tools schema must be composed before SolveigConfig().tools has real fields."""
    bootstrap.compose_core_tools()


async def test_api_type_from_string_and_serializes_to_name():
    c = ApiConfig(type="openai")
    assert c.type.name == "openai"
    assert c.model_dump()["type"] == c.type.name


async def test_theme_from_string_serializes_to_name():
    name = next(iter(themes.THEMES))
    c = TuiConfig(theme=name)
    assert c.theme is themes.THEMES[name]
    assert c.model_dump()["theme"] == themes.THEMES[name].name


async def test_command_enabled_default_true_and_regex_validated():
    assert CommandConfig().enabled is True
    # strings are compiled to patterns; a bad regex is rejected declaratively
    c = CommandConfig(auto_execute=["^ls "])
    assert c.auto_execute[0].match("ls -la")
    with pytest.raises(ValidationError):
        CommandConfig(auto_execute=["([unclosed"])


async def test_validate_assignment_reparses_theme():
    c = TuiConfig()
    name = next(iter(themes.THEMES))
    c.theme = name  # assignment must re-run the validator
    assert c.theme is themes.THEMES[name]


async def test_tool_allow_block():
    s = MCPServerConfig(
        name="s", url="u", allowed_tools=["get_*"], blocked_tools=["get_secret"]
    )
    assert s.is_tool_allowed("get_page")
    assert not s.is_tool_allowed("get_secret")
    assert not s.is_tool_allowed("post_x")


async def test_mcp_name_is_derived_from_the_url_when_not_given():
    # The name is joined onto every tool the server exposes, so it must be a
    # plain identifier even when the user only ever supplied an address.
    assert MCPServerConfig.from_url("https://search.parallel.ai/mcp").name == (
        "search_parallel_ai"
    )
    assert MCPServerConfig.from_url("stdio://uvx some-server --flag").name == "uvx"
    # an explicit name is taken as-is, and still has to be a valid identifier
    assert MCPServerConfig.from_url("https://x/mcp", "search").name == "search"
    with pytest.raises(ValueError, match="not a valid identifier"):
        MCPServerConfig.from_url("https://x/mcp", "not.a.name")


async def test_mcp_name_is_not_dumped_into_its_own_block():
    # The name's home on disk is the KEY of the block; writing it inside as well
    # would be a second home for one value, free to disagree on the next edit.
    assert "name" not in MCPServerConfig(name="s", url="u").model_dump()


async def test_tools_nesting_defaults():
    t = SolveigConfig(cli_args=[]).tools
    assert t.http.maximum_response_size == 1024**3  # default is 1 GiB
    assert t.command.enabled is True


async def test_every_core_tool_has_an_entry_and_is_enabled_by_default():
    t = SolveigConfig(cli_args=[]).tools
    for name in (
        "command",
        "http",
        "read",
        "write",
        "edit",
        "delete",
        "copy",
        "move",
        "todo",
    ):
        assert getattr(t, name).enabled is True


async def test_http_and_command_inherit_enabled_from_base():
    # HttpConfig/CommandConfig extend ToolConfig; `enabled` is inherited, not redeclared.
    assert issubclass(HttpConfig, ToolConfig)
    assert issubclass(CommandConfig, ToolConfig)
    assert HttpConfig().enabled is True
    assert HttpConfig(enabled=False).enabled is False


async def test_system_prompt_defaults():
    from solveig.config import DEFAULT_SYSTEM_PROMPT

    sp = SystemPromptConfig()
    assert sp.content == DEFAULT_SYSTEM_PROMPT
    assert sp.add_examples is False
    assert sp.add_os_info is False
