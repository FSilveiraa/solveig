import pytest
from pydantic import ValidationError

from solveig.api import APIType
from solveig.config.models import (
    ApiConfig,
    CommandConfig,
    HttpConfig,
    InterfaceConfig,
    McpConfig,
    MCPServerConfig,
    SystemPromptConfig,
    ToolConfig,
    ToolsConfig,
)
from solveig.interface import themes


def test_api_type_from_string_and_serializes_to_name():
    c = ApiConfig(type="anthropic")
    assert c.type is APIType.ANTHROPIC
    assert c.model_dump()["type"] == "anthropic"


def test_theme_from_string_serializes_to_name():
    name = next(iter(themes.THEMES))
    c = InterfaceConfig(theme=name)
    assert c.theme is themes.THEMES[name]
    assert c.model_dump()["theme"] == themes.THEMES[name].name


def test_command_enabled_default_true_and_regex_validated():
    assert CommandConfig().enabled is True
    # strings are compiled to patterns; a bad regex is rejected declaratively
    c = CommandConfig(auto_execute=["^ls "])
    assert c.auto_execute[0].match("ls -la")
    with pytest.raises(ValidationError):
        CommandConfig(auto_execute=["([unclosed"])


def test_validate_assignment_reparses_theme():
    c = InterfaceConfig()
    name = next(iter(themes.THEMES))
    c.theme = name  # assignment must re-run the validator
    assert c.theme is themes.THEMES[name]


def test_mcp_servers_key_injected_as_url():
    m = McpConfig(servers={"stdio://echo": {"name": "e"}})
    assert m.servers["stdio://echo"].url == "stdio://echo"
    assert m.servers["stdio://echo"].name == "e"


def test_tool_allow_block():
    s = MCPServerConfig(url="u", allowed_tools=["get_*"], blocked_tools=["get_secret"])
    assert s.is_tool_allowed("get_page")
    assert not s.is_tool_allowed("get_secret")
    assert not s.is_tool_allowed("post_x")


def test_tools_nesting_defaults():
    t = ToolsConfig()
    assert t.http.max_response_bytes == 50_000
    assert t.command.enabled is True


def test_every_core_tool_has_an_entry_and_is_enabled_by_default():
    t = ToolsConfig()
    for name in (
        "command",
        "http",
        "read",
        "write",
        "edit",
        "delete",
        "copy",
        "move",
        "tasks",
    ):
        assert getattr(t, name).enabled is True


def test_http_and_command_inherit_enabled_from_base():
    # HttpConfig/CommandConfig extend ToolConfig; `enabled` is inherited, not redeclared.
    assert issubclass(HttpConfig, ToolConfig)
    assert issubclass(CommandConfig, ToolConfig)
    assert HttpConfig().enabled is True
    assert HttpConfig(enabled=False).enabled is False


def test_system_prompt_defaults():
    from solveig.config.models import DEFAULT_SYSTEM_PROMPT

    sp = SystemPromptConfig()
    assert sp.content == DEFAULT_SYSTEM_PROMPT
    assert sp.add_examples is False
    assert sp.add_os_info is False
