from solveig.config import SolveigConfig
"""Unit tests for config.editor.prompt_for_field."""

import pytest

from solveig.api.types import APIType, TYPE_BY_NAME
from solveig.config.editor import prompt_for_field
from solveig.interface import themes
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Bool fields → ask_choice (True / False)
# ---------------------------------------------------------------------------


async def test_bool_field_returns_true():
    """Choosing index 0 for a bool field returns True."""
    config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump())
    result = await prompt_for_field("disable_autonomy", config, MockInterface(choices=[0]))
    assert result is True


async def test_bool_field_returns_false():
    """Choosing index 1 for a bool field returns False."""
    config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump())
    result = await prompt_for_field("disable_autonomy", config, MockInterface(choices=[1]))
    assert result is False


# ---------------------------------------------------------------------------
# Constrained-choice fields
# ---------------------------------------------------------------------------


async def test_theme_returns_theme_object():
    """prompt_for_field for 'theme' returns the corresponding Palette object."""
    config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump())
    result = await prompt_for_field("interface.theme", config, MockInterface(choices=[0]))
    assert result is list(themes.THEMES.values())[0]


async def test_code_theme_returns_string():
    """prompt_for_field for 'code_theme' returns a valid code theme string."""
    code_theme_options = sorted(themes.CODE_THEMES)
    config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump())
    result = await prompt_for_field("interface.code_theme", config, MockInterface(choices=[0]))
    assert result == code_theme_options[0]


async def test_api_type_returns_api_type_value():
    """prompt_for_field for 'api.type' returns the corresponding APIType instance."""
    config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump())
    result = await prompt_for_field("api.type", config, MockInterface(choices=[0]))
    assert isinstance(result, APIType)
    assert result.display_value() in TYPE_BY_NAME


# ---------------------------------------------------------------------------
# List fields → ask_question, split on comma
# ---------------------------------------------------------------------------


async def test_list_field_single_item():
    """A single value for a list field returns a one-element list."""
    config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump(), briefing=[])
    result = await prompt_for_field(
        "briefing", config, MockInterface(user_inputs=["BRIEFING.md"])
    )
    assert result == ["BRIEFING.md"]


async def test_list_field_multiple_items():
    """Comma-separated input for a list field returns all items stripped."""
    config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump(), auto_allowed_paths=[])
    result = await prompt_for_field(
        "auto_allowed_paths", config, MockInterface(user_inputs=["a, b, c"])
    )
    assert result == ["a", "b", "c"]


async def test_list_field_empty_string_returns_empty():
    """Empty string input for a list field returns an empty list."""
    config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump(), briefing=["old.md"])
    result = await prompt_for_field("briefing", config, MockInterface(user_inputs=[""]))
    assert result == []


# ---------------------------------------------------------------------------
# Free-text fields (str, int, float, str | None)
# ---------------------------------------------------------------------------


async def test_str_field_returns_string():
    """Free-text input for a str field is returned as-is."""
    config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump())
    result = await prompt_for_field(
        "api.model", config, MockInterface(user_inputs=["gpt-4o"])
    )
    assert result == "gpt-4o"


async def test_str_or_none_empty_returns_none():
    """Empty input for an optional str field (model) returns None."""
    config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump() | {"api.model": None})
    result = await prompt_for_field("api.model", config, MockInterface(user_inputs=[""]))
    assert result is None


async def test_int_field_returns_int():
    """Free-text input for an int field is parsed to int."""
    config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump() | {"api.max_context": 4096})
    result = await prompt_for_field(
        "api.max_context", config, MockInterface(user_inputs=["8192"])
    )
    assert result == 8192


async def test_float_field_returns_float():
    """Free-text input for a float field is parsed to float."""
    config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump() | {"api.temperature": 0.0})
    result = await prompt_for_field(
        "api.temperature", config, MockInterface(user_inputs=["0.7"])
    )
    assert result == pytest.approx(0.7)
